"""Portable, versioned exports with an explicit dependency and privacy boundary."""

from __future__ import annotations

import copy
import io
import json
import os
import re
import stat
import uuid
import zipfile
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..db import Record, Revision, db, now
from .common import context_text, markdown_record, require

router = APIRouter()
PORTABLE = {
    "source",
    "person",
    "cognitive_profile",
    "distillation",
    "chapter",
    "card",
    "agent",
    "conversation",
    "message",
    "artifact",
    "skill",
    "run",
    "memory",
    "relation",
}
PRIVATE_KEYS = {
    "api_key",
    "secret",
    "secret_key",
    "password",
    "authorization",
    "service_token",
    "file_path",
    "original_path",
    "vectors",
    "vector",
    "embeddings",
    "embedding",
    "image_path",
    "parsed_path",
    "access_token",
    "refresh_token",
    "api_token",
    "bearer_token",
    "client_secret",
    "private_key",
    "credentials",
    "owner_user_id",
    "legacy_agent_binding",
}
PRIVATE_NORMALIZED = {re.sub(r"[^a-z0-9]", "", key.lower()) for key in PRIVATE_KEYS}
REFERENCE_FIELDS = {
    "source_id",
    "chapter_id",
    "card_id",
    "agent_id",
    "conversation_id",
    "skill_id",
    "run_id",
    "message_id",
    "from_id",
    "to_id",
    "parent_id",
    "distillation_id",
    "active_distillation_id",
    "person_id",
    "cognitive_profile_id",
}
REFERENCE_LISTS = {
    "source_ids",
    "raw_source_ids",
    "chapter_ids",
    "card_ids",
    "agent_ids",
    "message_ids",
    "source_message_ids",
    "response_to",
    "excluded_card_ids",
    "shared_card_ids",
    "shared_agent_ids",
    "missing_source_ids",
}
REFERENCE_MAPS = {
    "source_versions",
    "distillation_ids",
    "chapter_versions",
    "card_versions",
    "agent_snapshots",
    "node_labels",
    "excluded_card_versions",
}
MAX_PACKAGE = 100 * 1024 * 1024
MAX_EXPANDED = 500 * 1024 * 1024


def folder() -> Path:
    path = Path(os.getenv("MINDCHIME_DATA_DIR", "data")).resolve() / "transfers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dependency_ids(value, field=None) -> set[str]:
    if isinstance(value, str):
        return {value} if field in REFERENCE_FIELDS or field in REFERENCE_LISTS else set()
    if isinstance(value, dict):
        found = set(value) if field in REFERENCE_MAPS else set()
        if (
            isinstance(value.get("kind"), str)
            and value["kind"] in PORTABLE
            and isinstance(value.get("id"), str)
        ):
            found.add(value["id"])
        if field == "distillation_ids":
            found |= {v for v in value.values() if isinstance(v, str)}
        if field == "integration":
            found |= {relation[key] for relation in value.get("relationships", []) if isinstance(relation, dict)
                      for key in ("from", "to") if isinstance(relation.get(key), str)}
        for key, item in value.items():
            found |= dependency_ids(item, key)
        return found
    if isinstance(value, list):
        return set().union(*(dependency_ids(item, field) for item in value)) if value else set()
    return set()


def referenced_ids(value, known: set[str]) -> set[str]:
    return dependency_ids(value) & known


def select_records(kind: str, id: str | None):
    all_records = {r["id"]: r for r in db.list() if r["kind"] in PORTABLE}
    if kind == "workspace":
        return list(all_records.values())
    item = require(id or "", kind)
    selected = {item["id"]}
    if kind == "source":
        selected |= {
            r["id"]
            for r in all_records.values()
            if r["kind"] in {"chapter", "card", "distillation"}
            and (r.get("parent_id") == id or id in r["data"].get("source_ids", []))
        }
    if kind == "conversation":
        selected |= {
            r["id"]
            for r in all_records.values()
            if r["kind"] in {"message", "artifact"}
            and (r.get("parent_id") == id or r["data"].get("conversation_id") == id)
        }
    if kind == "skill":
        selected |= {r["id"] for r in all_records.values() if r["kind"] == "run" and r.get("parent_id") == id}
    while True:
        expanded = set(selected)
        for current in selected:
            record = all_records.get(current)
            if record:
                expanded |= referenced_ids(record["data"], set(all_records))
                # Historical conversation/Agent snapshots need their own dependency closure.
                for revision in db.revisions(current):
                    expanded |= referenced_ids(revision["data"], set(all_records))
                if record.get("parent_id") in all_records:
                    expanded.add(record["parent_id"])
        if expanded == selected:
            break
        selected = expanded
    return [all_records[id] for id in selected if id in all_records]


def clean(value, include_originals: bool):
    if isinstance(value, list):
        return [clean(v, include_originals) for v in value]
    if not isinstance(value, dict):
        return value
    result = {
        k: clean(v, include_originals)
        for k, v in value.items()
        if re.sub(r"[^a-z0-9]", "", k.lower()) not in PRIVATE_NORMALIZED
    }
    if result.get("kind") == "chapter" and not include_originals:
        result["data"]["text"] = ""
        result["data"]["original_omitted"] = True
    return result


def validate_manifest(manifest: dict):
    if (
        not isinstance(manifest, dict)
        or manifest.get("format") != "mindchime"
        or manifest.get("version") != 1
    ):
        raise HTTPException(422, "不支持的资产包格式或版本")
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) > 10000:
        raise HTTPException(422, "资产包记录数无效或超限")
    seen = set()
    kinds, versions = {}, {}

    def validate_links(value):
        if isinstance(value, list):
            for child in value:
                validate_links(child)
        elif isinstance(value, dict):
            for key, child in value.items():
                if key in REFERENCE_LISTS and (
                    not isinstance(child, list) or any(not isinstance(item, str) for item in child)
                ):
                    raise HTTPException(422, "资产依赖列表格式无效")
                if key in REFERENCE_FIELDS and child is not None and not isinstance(child, str):
                    raise HTTPException(422, "资产依赖编号格式无效")
                if key in REFERENCE_MAPS and not isinstance(child, dict):
                    raise HTTPException(422, "版本依赖映射格式无效")
                if key == "distillation_ids" and any(not isinstance(value, str) for value in child.values()):
                    raise HTTPException(422, "蒸馏结果选择映射必须使用字符串编号")
                validate_links(child)

    for record in records:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("kind"), str)
            or record["kind"] not in PORTABLE
            or not isinstance(record.get("data"), dict)
        ):
            raise HTTPException(422, "资产包包含不允许的记录类型")
        id = record.get("id")
        if not isinstance(id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", id) or id in seen:
            raise HTTPException(422, "资产包包含无效或重复的记录ID")
        seen.add(id)
        kinds[id] = record["kind"]
        if not isinstance(record.get("title"), str) or len(record["title"]) > 1000:
            raise HTTPException(422, "资产包标题无效")
        if type(record.get("version")) is not int or not 1 <= record["version"] <= 1000000:
            raise HTTPException(422, "资产包版本无效")
        versions[id] = record["version"]
        if not isinstance(record.get("status"), str) or len(record["status"]) > 50:
            raise HTTPException(422, "资产状态无效")
        validate_links(record)
    revisions = manifest.get("revisions", [])
    if not isinstance(revisions, list) or len(revisions) > 100000:
        raise HTTPException(422, "版本记录无效或过多")
    seen_versions = set()
    for revision in revisions:
        if (
            not isinstance(revision, dict)
            or revision.get("id") not in seen
            or not isinstance(revision.get("data"), dict)
        ):
            raise HTTPException(422, "版本记录没有对应资产")
        key = (revision["id"], revision.get("version"))
        if (
            type(revision.get("version")) is not int
            or not 1 <= revision["version"] <= versions[revision["id"]]
        ):
            raise HTTPException(422, "历史版本编号无效")
        if revision.get("kind") != kinds[revision["id"]] or key in seen_versions:
            raise HTTPException(422, "历史版本类型不一致或重复")
        if not isinstance(revision.get("title"), str) or not isinstance(revision.get("status"), str):
            raise HTTPException(422, "历史版本标题或状态无效")
        seen_versions.add(key)
        validate_links(revision)
    originals = manifest.get("originals", [])
    if not isinstance(originals, list):
        raise HTTPException(422, "原文件清单无效")
    original_sources = set()
    for original in originals:
        if not isinstance(original, dict) or kinds.get(original.get("source_id")) != "source":
            raise HTTPException(422, "原文件必须关联包内资料")
        if original["source_id"] in original_sources:
            raise HTTPException(422, "同一资料不能重复指定原始文件")
        original_sources.add(original["source_id"])
    return records


def read_package(content: bytes):
    if len(content) > MAX_PACKAGE:
        raise HTTPException(413, "资产包最多 100 MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        infos = archive.infolist()
        if len(infos) > 10001 or sum(i.file_size for i in infos) > MAX_EXPANDED:
            raise HTTPException(413, "资产包展开后的内容超限")
        names = set()
        for info in infos:
            path = Path(info.filename)
            if info.filename in names or path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise HTTPException(422, "资产包路径不安全")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise HTTPException(422, "资产包不允许符号链接")
            if info.filename != "manifest.json" and not re.fullmatch(
                r"originals/[A-Za-z0-9_.-]+", info.filename
            ):
                raise HTTPException(422, "资产包包含未知文件")
            names.add(info.filename)
        info = archive.getinfo("manifest.json")
        if info.file_size > 50 * 1024 * 1024:
            raise HTTPException(413, "清单文件过大")
        manifest = json.loads(archive.read("manifest.json"))
        validate_manifest(manifest)
        for entry in manifest.get("originals", []):
            if entry.get("path") not in names or not str(entry.get("path")).startswith("originals/"):
                raise HTTPException(422, "原文件清单与资产包不一致")
        return archive, manifest
    except HTTPException:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
        UnicodeError,
    ) as exc:
        raise HTTPException(422, "无法读取资产包或缺少有效清单") from exc


def managed_original(path):
    base = folder().parent
    actual = Path(path).resolve()
    originals = (base / "originals").resolve()
    transfers = (base / "transfers").resolve()
    allowed = actual.is_relative_to(originals) or (
        actual.parent == transfers and re.fullmatch(r"original-[A-Za-z0-9_-]+\.[A-Za-z0-9]{1,8}", actual.name)
    )
    if not allowed:
        raise HTTPException(422, "原文件路径不在受管导入目录内，不能读取或导出")
    return actual


@router.get("/export")
def export(kind: str = "workspace", id: str | None = None, format: str = "zip", originals: bool = False):
    from ..access import is_admin, identity
    if is_admin():
        with identity(None):
            return _export(kind,id,format,originals)
    return _export(kind,id,format,originals)


def _export(kind: str = "workspace", id: str | None = None, format: str = "zip", originals: bool = False):
    if kind not in {"workspace", "source", "agent", "conversation", "artifact", "skill", "distillation", "person", "cognitive_profile", "run"}:
        raise HTTPException(422, "不支持的导出类型")
    if format not in {"zip", "markdown"}:
        raise HTTPException(422, "请选择 Markdown 或 ZIP")
    from ..access import is_admin, PRIVATE_KINDS
    if not is_admin() and (kind not in {"conversation","artifact","run"} or originals):
        raise HTTPException(403,"普通用户仅可导出自己的对话、成果或实践记录")
    records = select_records(kind, id)
    if not is_admin():
        records = [r for r in records if r["kind"] in PRIVATE_KINDS]
    item = next((r for r in records if r["id"] == id), None)
    name = item["title"] if item else "MindChime 个人资产"
    if format == "markdown":
        selected = records
        if kind == "conversation":
            selected = sorted(
                [r for r in records if r["kind"] == "message" and r["parent_id"] == id],
                key=lambda r: (r["created_at"], r["id"]),
            ) + [r for r in records if r["kind"] == "artifact" and r["data"].get("conversation_id") == id]
        elif kind == "source":
            selected = [r for r in records if r["kind"] == "card" and id in r["data"].get("source_ids", [])]
        elif item:
            selected = [item]
        sections = [f"# {name}", "", "来源状态与编辑标识保留；不包含模型凭据。", ""]
        if kind == "source" and item:
            data = item["data"]
            sections += ["## 资料总览", "", context_text(data.get("distillation") or "尚无整合结果"),
                         "", "## 覆盖与处理报告", "", context_text(data.get("coverage") or "尚无蒸馏覆盖报告"), "", "## 章节摘要", ""]
            for chapter in records:
                if chapter["kind"] == "chapter" and chapter["id"] in data.get("chapter_ids", []):
                    sections += [f"### {chapter['title']}", "", chapter["data"].get("latest_summary") or "未处理或未生成摘要", ""]
        if kind == "distillation" and item:
            from ..distillation.store import result_detail
            result = result_detail(item["id"])
            data = result["data"]
            sections += ["## 方法与版本", context_text(data.get("method", {})),
                "## 提示词", data.get("prompt", ""), "## 总览", context_text(data.get("integration", {})),
                "## 章节摘要", context_text(data.get("chapter_summaries", [])),
                "## 覆盖与质量", context_text(data.get("coverage", {})), context_text(data.get("quality", {})),
                "## 方法特色成果", context_text(data.get("extensions", [])), "## 提醒", context_text(data.get("warnings", []))]
            selected = result["cards"]
        if kind == "agent":
            selected = [item] + [r for r in records if r["kind"] == "card"]
        for record in selected:
            if record["kind"] == "message":
                data = record["data"]
                sections += [
                    f"## {data.get('speaker_name') or record['title']} · {record['created_at']}",
                    "",
                    f"状态：{record['status']}",
                    "",
                    data.get("text", data.get("content", "")),
                    "",
                ]
                sections += [
                    f"- 引用：{ref.get('label', ref.get('source_id', ''))} / {ref.get('chapter_id', '')}"
                    for ref in data.get("references", [])
                ]
            elif record["kind"] not in {"source", "chapter"}:
                sections.append(markdown_record(record))
        extension = "md"
        content = "\n".join(sections).encode()
        media_type = "text/markdown; charset=utf-8"
    else:
        manifest = {
            "format": "mindchime",
            "version": 1,
            "exported_at": now(),
            "records": clean(records, originals),
            "revisions": clean([rev for r in records for rev in db.revisions(r["id"])], originals),
            "originals": [],
            "publications": [],
            "notes": [
                "模型凭据和服务配置未导出；导入后请重新指定模型。",
                "向量索引未导出，需确认模型后重新建立。",
            ],
            "missing_originals": [],
        }
        from ..publications import all_publications
        selected_ids={r["id"] for r in records}
        if is_admin():
            manifest["publications"] = clean([p for p in all_publications(history=True) if p["record_id"] in selected_ids], originals)
            manifest["notes"].append("发布记录仅作核对，恢复后需要管理员重新检查并发布；个人内容归导入账号，原账号凭据不迁移。")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for source in (r for r in records if r["kind"] == "source"):
                path = source["data"].get("file_path")
                actual = managed_original(path) if originals and path else None
                if actual and actual.is_file():
                    suffix = actual.suffix.lower()
                    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
                        suffix = ".bin"
                    member = f"originals/{source['id']}{suffix}"
                    archive.write(actual, member)
                    manifest["originals"].append({"source_id": source["id"], "path": member})
                else:
                    manifest["missing_originals"].append(source["id"])
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        content = output.getvalue()
        extension, media_type = "zip", "application/zip"
    filename = "SKILL.md" if kind == "skill" and format == "markdown" else f"{name}.{extension}"
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename)},
    )


@router.post("/imports/preview")
async def preview(file: Annotated[UploadFile, File()]):
    content = await file.read(MAX_PACKAGE + 1)
    archive, manifest = read_package(content)
    archive.close()
    records = manifest["records"]
    counts = {}
    for record in records:
        counts[record["kind"]] = counts.get(record["kind"], 0) + 1
    conflicts = [
        {"id": r["id"], "title": r["title"], "kind": r["kind"]}
        for r in records
        if db.get(r["id"], include_deleted=True)
    ]
    existing_ids = {r["id"] for r in records}
    missing = [
        {"id": r["id"], "dependency": value}
        for r in records
        for value in sorted(dependency_ids(r) - existing_ids)
    ]
    temp_id = str(uuid.uuid4())
    path = folder() / f"{temp_id}.zip"
    path.write_bytes(content)
    os.chmod(path, 0o600)
    info = {
        "counts": counts,
        "conflicts": conflicts,
        "missing": missing,
        "includes_originals": bool(manifest.get("originals")),
        "notes": manifest.get("notes", []),
        "path": str(path),
    }
    db.create("import_preview", file.filename or "资产包", info, status="preview", id=temp_id)
    return {"id": temp_id, **{k: v for k, v in info.items() if k != "path"}}


def remap(value, mapping, field=None):
    if isinstance(value, str):
        return mapping.get(value, value) if field in REFERENCE_FIELDS or field in REFERENCE_LISTS else value
    if isinstance(value, list):
        return [remap(item, mapping, field) for item in value]
    if isinstance(value, dict):
        result = {
            (mapping.get(key, key) if field in REFERENCE_MAPS else key): remap(item, mapping, key)
            for key, item in value.items()
        }
        if field == "distillation_ids":
            result = {mapping.get(k, k): mapping.get(v, v) for k, v in value.items()}
        if field == "integration":
            for relation in result.get("relationships", []):
                if isinstance(relation, dict):
                    for key in ("from", "to"):
                        if isinstance(relation.get(key), str):
                            relation[key] = mapping.get(relation[key], relation[key])
        if (
            isinstance(value.get("kind"), str)
            and value["kind"] in PORTABLE
            and isinstance(value.get("id"), str)
        ):
            result["id"] = mapping.get(value["id"], value["id"])
        return result
    return value


def sanitize_restored(value):
    if isinstance(value, list):
        return [sanitize_restored(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: sanitize_restored(item) for key, item in value.items() if key != "model_profile_id"}
    kind = result.get("kind")
    data = result.get("data")
    if not isinstance(kind, str) or kind not in PORTABLE or not isinstance(data, dict):
        return result
    if kind in {"skill","run"}:
        for key in ("agent_id","agent_version","agent_snapshot","legacy_agent_binding"):
            data.pop(key,None)
        data["migration_notice"] = "独立实践不再依赖人物智能体，历史步骤保留。"
    if kind == "source":
        data.update(original_missing=True, original_available=False, file_path=None)
    if kind in {"agent", "skill"}:
        data.update(model_profile_id=None, import_notice="请核对知识范围并重新选择模型")
    if kind == "memory" and result.get("status") == "active":
        result["status"] = "candidate"
        data["confirmed"] = False
    if kind == "chapter" and data.get("original_omitted"):
        data["text"] = ""
    return result


@router.post("/imports/{id}/restore")
def restore(id: str, body: dict):
    info = require(id, "import_preview")
    if info["status"] == "completed":
        if body.get("conflict", "copy") != info["data"].get("restore_conflict", "copy"):
            raise HTTPException(409, "该预览已按另一种冲突规则恢复，请重新上传预览")
        return info["data"]["result"]
    if info["status"] != "preview":
        raise HTTPException(409, "该导入已开始或失败，请重新预览")
    conflict = body.get("conflict", "copy")
    if conflict not in {"copy", "skip"}:
        raise HTTPException(422, "请选择另存副本或跳过冲突")
    preview_path = Path(info["data"]["path"]).resolve()
    if preview_path.parent != folder() or preview_path.name != f"{id}.zip":
        raise HTTPException(422, "导入预览路径无效，请重新上传资产包")
    archive, manifest = read_package(preview_path.read_bytes())
    records = manifest["records"]
    mapping = {r["id"]: str(uuid.uuid4()) for r in records}
    package_ids = set(mapping)
    missing_ids = dependency_ids(records + manifest.get("revisions", [])) - package_ids
    # Never attach package references to unrelated records already on this instance.
    mapping.update(
        {
            missing: "missing-" + uuid.uuid5(uuid.NAMESPACE_URL, f"{id}:{missing}").hex
            for missing in missing_ids
        }
    )
    skipped = set()
    if conflict == "skip":
        skipped = {r["id"] for r in records if db.get(r["id"], include_deleted=True)}
        # Do not attach imported derivatives to a different existing revision.
        while True:
            extended = skipped | {
                r["id"]
                for r in records
                if referenced_ids(r["data"], skipped) or r.get("parent_id") in skipped
            }
            if extended == skipped:
                break
            skipped = extended
    try:
        db.update(
            id, status="restoring", data={"restore_conflict": conflict}, expected_version=info["version"]
        )
    except ValueError:
        archive.close()
        latest = require(id, "import_preview")
        if latest["status"] == "completed" and latest["data"].get("restore_conflict") == conflict:
            return latest["data"]["result"]
        raise HTTPException(409, "该导入正在处理，请等待结果；不会重复导入") from None
    created, files = [], []
    try:
        for record in records:
            if record["id"] in skipped:
                continue
            item = sanitize_restored(clean(remap(copy.deepcopy(record), mapping), include_originals=True))
            missing = dependency_ids(record) & missing_ids
            if missing:
                item["data"]["missing_dependency_ids"] = sorted(missing)
                item["data"]["disabled_reason"] = "资产包缺少依赖，未连接到本实例的同名或同编号资料"
                if item["kind"] in {"agent", "skill", "run", "relation", "memory", "card", "distillation", "cognitive_profile"}:
                    item["status"] = "disabled"
            db.create(
                item["kind"],
                item["title"],
                item["data"],
                status=item["status"],
                parent_id=item.get("parent_id"),
                id=item["id"],
            )
            created.append(item["id"])
            revisions = [r for r in manifest.get("revisions", []) if r["id"] == record["id"]]
            revisions = sanitize_restored(clean(remap(revisions, mapping), include_originals=True))
            with Session(db.engine) as session, session.begin():
                current = session.get(Record, item["id"])
                current.version = item["version"]
                session.execute(delete(Revision).where(Revision.record_id == item["id"]))
                snapshots = {
                    r["version"]: r
                    for r in revisions
                    if isinstance(r.get("version"), int) and 0 < r["version"] < item["version"]
                }
                snapshots[item["version"]] = {
                    **item,
                    "created_at": current.created_at,
                    "updated_at": current.updated_at,
                }
                for version, snapshot in snapshots.items():
                    session.add(Revision(record_id=item["id"], version=version, snapshot=snapshot))
        for original in manifest.get("originals", []):
            if original["source_id"] in skipped:
                continue
            source_id = mapping.get(original["source_id"])
            if not source_id or source_id not in created:
                continue
            suffix = Path(original["path"]).suffix
            destination = folder() / f"original-{source_id}{suffix}"
            destination.write_bytes(archive.read(original["path"]))
            files.append(destination)
            os.chmod(destination, 0o600)
            db.update(
                source_id,
                data={"file_path": str(destination), "original_missing": False, "original_available": True},
            )
        result = {
            "restored": len(created),
            "skipped": len(skipped),
            "id_mapping": {
                old: new for old, new in mapping.items() if old in package_ids and old not in skipped
            },
            "notes": [
                "模型配置未导入，请检查默认模型。",
                "记忆需要重新确认；原始文件缺失时仅保留允许导出的引用片段。",
            ],
        }
        db.update(id, status="completed", data={"result": result})
        Path(info["data"]["path"]).unlink(missing_ok=True)
        return result
    except Exception:
        for record_id in reversed(created):
            db.purge(record_id)
        for path in files:
            path.unlink(missing_ok=True)
        db.update(id, status="failed")
        raise
    finally:
        archive.close()
