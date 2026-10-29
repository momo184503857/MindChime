from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import delete, func, select

from .db import db, Event
from .domain import (agent_data, agent_in_conversation, chapters_for, conversation_messages,
                     knowledge_summary, register_handlers, require, save_message, snapshots, source_ids, validate_sources, source_usable)
from .jobs import ACTIVE, AI_URL, ai_headers, emit_job, enqueue, purge_ai_requests, settings
from .parsers import parse_document, text_sections
from .worker import Worker

DATA_DIR = Path(os.getenv("MINDCHIME_DATA_DIR", "data")).resolve()
router = APIRouter(prefix="/api/v1")
worker = Worker()


@asynccontextmanager
async def lifespan(app):
    register_handlers()
    from .enhancements import register_handlers as register_extra
    register_extra()
    from .distillation.store import migrate_legacy
    migrate_legacy()
    stamp = datetime.now(timezone.utc).isoformat()
    if db.get("business-runtime"):
        db.update("business-runtime", data={"started_at": stamp, "heartbeat": stamp}, status="running")
    else:
        db.create("runtime", "Business API", {"started_at": stamp, "heartbeat": stamp}, status="running", id="business-runtime")
    async def heartbeat():
        while True:
            db.update("business-runtime", data={"heartbeat": datetime.now(timezone.utc).isoformat()})
            await asyncio.sleep(2)
    heartbeat_task = asyncio.create_task(heartbeat())
    if os.getenv("MINDCHIME_EMBEDDED_WORKER") == "1":
        await worker.start()
    yield
    heartbeat_task.cancel()
    db.update("business-runtime", status="stopped")
    if os.getenv("MINDCHIME_EMBEDDED_WORKER") == "1":
        await worker.close()


app = FastAPI(title="MindChime", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?", allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(KeyError)
async def missing_error(request, exc):
    return JSONResponse(status_code=404, content={"detail": "对象不存在或已删除。"})


@app.exception_handler(httpx.HTTPError)
async def upstream_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "独立 AI 服务暂不可用，请检查服务状态后重试。"})


def get(record_id, kind=None):
    value = db.get(record_id, kind)
    if not value:
        raise HTTPException(404, "对象不存在或已删除。")
    return value


def title(value, maximum=100):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("标题、名称或议题不能为空。")
    if len(value.strip()) > maximum:
        raise ValueError(f"最多允许 {maximum} 个字符。")
    return value.strip()


def config_record():
    existing = db.list("settings")
    return existing[0] if existing else db.create("settings", "本地设置", {
        "max_file_mb": 50, "max_distill_characters": 500000, "max_concurrent_tasks": 1,
        "purpose_profiles": {}, "theme": "system", "diagnostics_enabled": False})


async def proxy(method, path, body=None):
    async with httpx.AsyncClient(base_url=AI_URL, headers=ai_headers(), timeout=45, trust_env=False) as client:
        response = await client.request(method, "/ai/v1"+path, json=body)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", "模型服务返回错误。")
        except ValueError:
            detail = "模型服务返回错误。"
        raise HTTPException(response.status_code, detail)
    return response.json() if response.content else {"ok": True}


async def ensure_model(purpose, profile_id=None):
    config = settings()
    profile_id = profile_id or config.get("purpose_profiles", {}).get(purpose) or config.get("default_profile_id")
    if not profile_id:
        raise HTTPException(409, f"请先在模型设置中配置 {purpose} 模型。")
    profiles = await proxy("GET", "/profiles")
    model = next((p for p in profiles if p["id"] == profile_id), None)
    if not model or not model.get("enabled", True) or not model.get("configured", True):
        raise HTTPException(409, "所选模型尚未配置或已停用，请先测试连接。")
    if purpose == "ocr" and not model.get("capabilities", {}).get("vision"):
        raise HTTPException(409, "OCR 需要配置支持图片输入的视觉模型。")
    return profile_id


@app.get("/health")
@router.get("/health")
def health():
    return {"status": "ok", "service": "mindchime", "mode": "local"}


@router.get("/dashboard")
def dashboard():
    kinds = ("source", "agent", "conversation", "card", "artifact", "skill", "job")
    counts = {k: len(db.list(k)) for k in kinds}
    return {"counts": counts, "sources": db.list("source")[:6], "agents": db.list("agent")[:6],
            "conversations": db.list("conversation")[:6], "jobs": db.list("job")[:10]}


@router.get("/settings")
def get_settings():
    return config_record()["data"]


@router.patch("/settings")
def patch_settings(body: dict):
    forbidden = {"api_key", "secret", "token"}
    if forbidden & body.keys():
        raise ValueError("模型密钥请保存到独立模型配置中。")
    for name, minimum, maximum in [("max_file_mb", 1, 500), ("max_distill_characters", 1000, 2000000), ("max_concurrent_tasks", 1, 8)]:
        if name in body and not minimum <= int(body[name]) <= maximum:
            raise ValueError(f"{name} 必须在 {minimum}–{maximum} 之间。")
    return db.update(config_record()["id"], data=body)["data"]


@router.get("/profiles")
async def list_profiles():
    return await proxy("GET", "/profiles")


@router.post("/profiles")
async def add_profile(body: dict):
    return await proxy("POST", "/profiles", body)


@router.patch("/profiles/{profile_id}")
async def edit_profile(profile_id: str, body: dict):
    return await proxy("PATCH", f"/profiles/{profile_id}", body)


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    affected = [a["title"] for a in db.list("agent") if a["data"].get("model_profile_id") == profile_id]
    if any(j["status"] in ACTIVE and (j["data"].get("input", {}).get("model_profile_id") == profile_id or any(s.get("profile_id") == profile_id for s in j["data"].get("steps", {}).values())) for j in db.list("job")):
        raise HTTPException(409, "此模型仍有未结束任务，请先结束任务。")
    result = await proxy("DELETE", f"/profiles/{profile_id}")
    return {"result": result, "affected_agents": affected}


@router.post("/profiles/{profile_id}/test")
async def test_profile(profile_id: str):
    return await proxy("POST", f"/profiles/{profile_id}/test", {})


def import_content(raw, filename, source_title=None, author="", duplicate_action="reject", source_id=None, demo=False):
    if duplicate_action not in {"reject", "copy", "version"}:
        raise ValueError("请选择进入已有资料、创建副本或新版本。")
    limit = int(settings().get("max_file_mb", 50))*1024*1024
    if len(raw) > limit:
        raise ValueError(f"文件超过 {limit//1024//1024} MB 限制，请拆分或调整设置。")
    fingerprint = hashlib.sha256(raw).hexdigest()
    duplicate = next((s for s in db.list("source") if s["data"].get("sha256") == fingerprint), None)
    if duplicate and duplicate_action not in {"copy", "version"}:
        raise HTTPException(409, {"message": "相同文件已存在，可打开已有资料、创建副本或作为新版本。", "source_id": duplicate["id"]})
    name = title(source_title or Path(filename).stem)
    same_title = next((s for s in db.list("source") if s["title"] == name), None)
    if same_title and not duplicate and duplicate_action == "reject":
        raise HTTPException(409, {"message": "同名资料内容不同，请选择新资料副本或新版本。", "source_id": same_title["id"]})
    parsed = parse_document(raw, filename)
    prior = None
    if duplicate_action == "version":
        prior = get(source_id or (duplicate or same_title or {}).get("id", ""), "source")
        assert_source_not_processing(prior["id"])
    if demo:
        for chapter in parsed["chapters"]:
            if chapter["title"].startswith("原创演示资料"):
                chapter["selected"] = False
                chapter["notice"] = "演示封面和使用说明，默认不纳入蒸馏；正文保留真实章节标题。"
    extension = Path(filename).suffix.lower()
    directory = DATA_DIR / "originals"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}{extension}"
    path.write_bytes(raw)
    os.chmod(path, 0o600)
    info = {"author": author or "", "filename": Path(filename).name, "file_path": str(path), "sha256": fingerprint,
            "format": parsed["format"], "characters": parsed["characters"], "warnings": parsed["warnings"], "demo": demo,
            "original_available": True, "source_ids": []}
    if duplicate_action == "version":
        from .distillation.store import invalidate_current
        invalidate_current(prior["id"])
        source = db.update(prior["id"], data=info, title=name, status=parsed["status"])
    else:
        source = db.create("source", name, info, status=parsed["status"])
    chapters = []
    for order, item in enumerate(parsed["chapters"]):
        chapters.append(db.create("chapter", item["title"], {**item, "source_id": source["id"], "source_ids": [source["id"]], "order": order}, parent_id=source["id"]))
    source = db.update(source["id"], data={"chapter_ids": [c["id"] for c in chapters], "chapter_versions": {c["id"]: c["version"] for c in chapters}})
    return {"source": source, "chapters": chapters, "warnings": parsed["warnings"]}


@router.get("/sources")
def sources():
    return db.list("source")


@router.post("/sources/import")
async def import_file(file: UploadFile = File(...), title: str | None = Form(None), author: str = Form(""),
                      duplicate_action: str = Form("reject"), source_id: str | None = Form(None)):
    limit = int(settings().get("max_file_mb", 50))*1024*1024
    raw = await file.read(limit+1)
    return import_content(raw, file.filename or "文件.txt", title, author, duplicate_action, source_id)


@router.post("/sources/paste")
def paste(body: dict):
    text = body.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("请粘贴非空文本。")
    return import_content(text.encode(), "粘贴资料.txt", body.get("title"), body.get("author", ""), body.get("duplicate_action", "reject"), body.get("source_id"))


@router.post("/demo/load")
def demo():
    path = Path(__file__).resolve().parents[2] / "book_agent_platform_PRD_v1.0.md"
    if not path.exists():
        path = Path.cwd() / "book_agent_platform_PRD_v1.0.md"
    document = path.read_text()
    records = []
    for section_no, ending, name in [("25.1", "25.2", "小步验证：演示手册"), ("25.2", "25.3", "边界与取舍：演示手册")]:
        existing = next((s for s in db.list("source") if s["data"].get("demo") and s["title"] == name), None)
        if existing:
            records.append(existing)
            continue
        text = document.split(f"### {section_no}", 1)[1].split(f"### {ending}", 1)[0]
        text = "# 原创演示资料（非真实出版物）\n" + "\n".join(text.splitlines()[1:])
        records.append(import_content(text.encode(), name+".md", name, "MindChime 原创演示", "copy", demo=True)["source"])
    return {"sources": records, "notice": "原创演示资料；蒸馏与聊天仍需真实配置模型。"}


@router.get("/sources/{source_id}")
def source_detail(source_id: str, version: int | None = None):
    live = get(source_id, "source")
    source = db.revision(source_id, version) if version is not None else live
    if not source:
        raise HTTPException(404, "资料版本不存在。")
    cards = [c for c in db.list("card") if source_id in source_ids(c["data"])]
    chapters = chapters_for(source_id)
    if version is not None:
        chapters = []
        for cid in source["data"].get("chapter_ids", []):
            wanted = source["data"].get("chapter_versions", {}).get(cid)
            chapter = db.revision(cid, wanted) if wanted else next((r for r in db.revisions(cid) if r["updated_at"] <= source["updated_at"]), None)
            if chapter and db.get(cid, "chapter"):
                chapters.append(chapter)
        cards = [revision for card in cards if (revision := next((r for r in db.revisions(card["id"]) if r["updated_at"] <= source["updated_at"]), None))]
    return {"source": source, "chapters": chapters, "cards": cards,
            "versions": [v for v in db.revisions(source_id) if v["data"].get("chapter_ids")], "agents": [a for a in db.list("agent") if source_id in a["data"].get("source_ids", [])]}


@router.patch("/sources/{source_id}")
def edit_source(source_id: str, body: dict):
    get(source_id, "source")
    data = body.get("data", {})
    allowed = {"author", "edition", "translator", "publication", "category", "notes"}
    return db.update(source_id, title=title(body["title"]) if "title" in body else None, data={k: v for k, v in data.items() if k in allowed})


@router.get("/sources/{source_id}/file")
def source_file(source_id: str, version: int | None = None):
    source = get(source_id, "source")
    if source["status"] in {"file_deleted", "deleting", "cleaning", "disabled"}:
        raise HTTPException(410, "原始文件已删除或不可访问。")
    if version is not None:
        source = db.revision(source_id, version)
        if source is None:
            raise HTTPException(404, "来源版本不存在，不能改用其他版本。")
    path = source["data"].get("file_path")
    if not path or not Path(path).exists():
        raise HTTPException(410, "原始文件未导入或已删除。")
    return FileResponse(path, filename=source["data"].get("filename"), content_disposition_type="inline")


def affected_source(source_id):
    affected = {k: [] for k in ["card", "agent", "conversation", "message", "artifact", "skill", "run", "memory", "relation", "distillation", "job"]}
    for kind in affected:
        affected[kind] = [r for r in db.list(kind) if source_id in source_ids(r["data"]) or any(x.get("source_id") == source_id for x in r["data"].get("references", []))]
    agent_ids = {a["id"] for a in affected["agent"]}
    affected["conversation"] = [c for c in db.list("conversation") if set(c["data"].get("agent_ids", [])) & agent_ids]
    conv_ids = {c["id"] for c in affected["conversation"]}
    affected["job"] = [j for j in db.list("job") if source_id in source_ids(j["data"].get("input", {})) or j["data"].get("input", {}).get("conversation_id") in conv_ids]
    card_ids = {c["id"] for c in affected["card"]}
    for kind in ("skill", "relation"):
        affected[kind] = [r for r in db.list(kind) if source_id in source_ids(r["data"]) or set(r["data"].get("card_ids", [])) & card_ids or r["data"].get("from_id") in card_ids or r["data"].get("to_id") in card_ids]
    skill_ids = {s["id"] for s in affected["skill"]}
    affected["run"] = [r for r in db.list("run") if r["data"].get("skill_id") in skill_ids or source_id in source_ids(r["data"])]
    return affected


@router.get("/sources/{source_id}/impact")
def source_impact(source_id: str):
    get(source_id, "source")
    affected = affected_source(source_id)
    return {"counts": {k: len(v) for k, v in affected.items()}, "affected": affected,
            "notice": "删除派生知识会删除所有引用此资料的混合知识卡；其他原始资料不受影响。增强资产停用，历史摘录按所选范围处理。"}


def replace_without_revisions(record, data, status=None):
    db.purge(record["id"])
    return db.create(record["kind"], record["title"], data, status=status or record["status"], parent_id=record.get("parent_id"), id=record["id"])


def assert_source_not_processing(source_id):
    if any(j["status"] in ACTIVE and source_id in source_ids(j["data"].get("input", {})) for j in db.list("job")):
        raise HTTPException(409, "资料有未结束的处理任务，请先结束任务再修改原文或章节结构。")


def purge_event_cache():
    with db.engine.begin() as connection:
        high_water = connection.scalar(select(func.max(Event.id)))
        connection.execute(delete(Event))
        if high_water:
            connection.execute(Event.__table__.insert().values(id=high_water, topic="purged", event="purged", data={}, created_at=datetime.now(timezone.utc).isoformat()))


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, mode: str = "derived", history: str = "keep"):
    source = get(source_id, "source")
    if mode not in {"file", "derived"} or history not in {"keep", "redact"}:
        raise ValueError("删除范围无效。")
    affected = affected_source(source_id)
    db.update(source_id, status="deleting")
    cleanup_ok = True
    for job in affected["job"]:
        if job["status"] in ACTIVE:
            emit_job(db.update(job["id"], status="cancelled", data={"stage": "来源删除，任务已终止"}))
        cleanup_ok = await purge_ai_requests(job) and cleanup_ok
    # Pending worker calls must observe cancellation before their source records disappear.
    for _ in range(30):
        if not any((current := db.get(j["id"], "job")) and current["data"].get("active_step") for j in affected["job"]):
            break
        await asyncio.sleep(.2)
    if not cleanup_ok:
        db.update(source_id, data={"cleanup_pending": True, "cleanup_mode": mode, "cleanup_history": history})
        raise HTTPException(503, "独立 AI 服务副本清理尚未完成，资料已禁止继续使用。服务恢复后请重试删除。")
    for version in db.revisions(source_id):
        path = version["data"].get("file_path")
        if path:
            actual = Path(path).resolve()
            if actual.is_relative_to(DATA_DIR):
                actual.unlink(missing_ok=True)
    for chapter in db.list("chapter", parent_id=source_id, include_deleted=True):
        if mode == "derived":
            db.purge(chapter["id"])
        else:
            replace_without_revisions(chapter, {k: v for k, v in chapter["data"].items() if k not in {"text", "latest_summary"}}, "file_deleted")
    for vector in db.list("vector", include_deleted=True):
        if source_id in vector["data"].get("source_ids", []):
            db.purge(vector["id"])
    for job in affected["job"]:
        replace_without_revisions(job, {"kind": job["data"].get("kind"), "input": {"source_id": source_id}, "stage": "来源内容已清理", "steps": {}}, "cancelled")
    if mode == "derived":
        for result in affected["distillation"]:
            db.purge(result["id"])
        for card in affected["card"]:
            db.purge(card["id"])
        for kind in ("skill", "memory", "relation"):
            for item in affected[kind]:
                db.update(item["id"], status="disabled", data={"disabled_reason": "来源已删除", "missing_source_ids": [source_id]})
        for agent in affected["agent"]:
            availability = knowledge_summary(agent)
            db.update(agent["id"], status="incomplete" if availability["available"] else "disabled", data={"missing_source_ids": [source_id]})
        if history == "redact":
            for kind in ("message", "artifact", "run"):
                for item in affected[kind]:
                    replace_without_revisions(item, {"text": "[相关内容已按删除选择清除]", "content": "[相关内容已按删除选择清除]",
                        "source_ids": [], "references": [], "redacted": True, "role": item["data"].get("role"), "speaker_name": item["data"].get("speaker_name")}, "redacted")
        replace_without_revisions(source, {"deleted": True, "reason": "用户删除资料及派生知识"}, "deleted")
    else:
        data = {**source["data"], "file_path": None, "original_available": False, "cleanup_pending": False}
        replace_without_revisions(source, data, "file_deleted")
    # SSE is a transport cache, never the source of truth; discard private cached payloads.
    purge_event_cache()
    return {"ok": True, "mode": mode, "history": history, "counts": {k: len(v) for k, v in affected.items()}}


@router.get("/indexes")
def indexes():
    groups = {}
    for item in db.list("vector"):
        data = item["data"]
        key = (data["profile_id"], data["profile_version"], data["dimension"])
        group = groups.setdefault(key, {"profile_id": key[0], "profile_version": key[1], "dimension": key[2], "count": 0, "source_ids": set()})
        group["count"] += 1
        group["source_ids"].update(data.get("source_ids", []))
    return {"indexes": [{**value, "source_ids": sorted(value["source_ids"])} for value in groups.values()],
            "embedding_profile_id": settings().get("purpose_profiles", {}).get("embedding"),
            "mode": "hybrid" if settings().get("purpose_profiles", {}).get("embedding") else "keyword"}


@router.post("/indexes/rebuild")
async def start_rebuild(body: dict):
    ids = body.get("source_ids") or [s["id"] for s in db.list("source") if source_usable(s["id"], raw=True)]
    for sid in ids:
        get(sid, "source")
    validate_sources(ids)
    if not ids:
        raise ValueError("请先导入可用资料。")
    profile = await ensure_model("embedding", body.get("model_profile_id"))
    return enqueue("index_rebuild", {"source_ids": ids, "model_profile_id": profile}, body.get("request_id"))


@router.patch("/chapters/{chapter_id}")
def edit_chapter(chapter_id: str, body: dict):
    chapter = get(chapter_id, "chapter")
    assert_source_not_processing(chapter["data"]["source_id"])
    changes = {k: v for k, v in body.get("data", {}).items() if k in {"selected", "text"}}
    if "text" in changes:
        changes["user_corrected"] = True
    result = db.update(chapter_id, title=title(body["title"]) if "title" in body else None, data=changes)
    source = get(chapter["data"]["source_id"], "source")
    if "text" in changes and changes["text"] != chapter["data"].get("text"):
        from .distillation.store import invalidate_current
        invalidate_current(source["id"], chapter_id)
    db.update(source["id"], data={"chapter_versions": {**source["data"].get("chapter_versions", {}), chapter_id: result["version"]}})
    return result


@router.post("/chapters/merge")
def merge_chapters(body: dict):
    ids = list(dict.fromkeys(body.get("ids", [])))
    if len(ids) < 2:
        raise ValueError("至少选择两个章节。")
    chapters = [get(i, "chapter") for i in ids]
    source_id = chapters[0]["data"]["source_id"]
    assert_source_not_processing(source_id)
    if any(c["data"]["source_id"] != source_id for c in chapters):
        raise ValueError("不能跨资料合并章节。")
    source = get(source_id, "source")
    ordered = source["data"]["chapter_ids"]
    chapters.sort(key=lambda c: ordered.index(c["id"]))
    text = "\n\n".join(c["data"].get("text", "") for c in chapters)
    merged = db.create("chapter", " / ".join(c["title"] for c in chapters)[:100], {"source_id": source_id, "source_ids": [source_id], "text": text,
        "selected": True, "locator": {"type": "merged", "parts": [{"chapter_id": c["id"], "version": c["version"], "locator": c["data"].get("locator")} for c in chapters]}}, parent_id=source_id)
    new_ids = [merged["id"] if cid == chapters[0]["id"] else cid for cid in ordered if cid not in ids[1:]]
    # Preserve immutable old chapters for existing citations, remove them only from current source view.
    new_ids = [cid for cid in ordered if cid not in ids]
    new_ids.insert(min(ordered.index(cid) for cid in ids), merged["id"])
    from .distillation.store import invalidate_current
    invalidate_current(source_id)
    db.update(source_id, data={"chapter_ids": new_ids, "chapter_versions": {cid: get(cid, "chapter")["version"] for cid in new_ids}})
    return merged


@router.post("/chapters/{chapter_id}/split")
def split_chapter(chapter_id: str, body: dict):
    chapter = get(chapter_id, "chapter")
    assert_source_not_processing(chapter["data"]["source_id"])
    text = chapter["data"].get("text", "")
    offset = int(body.get("offset", 0))
    if not 0 < offset < len(text):
        raise ValueError("请选择章节正文中的拆分位置。")
    source = get(chapter["data"]["source_id"], "source")
    pieces = []
    for i, (start, end) in enumerate([(0, offset), (offset, len(text))], 1):
        pieces.append(db.create("chapter", f"{chapter['title']}（{i}）", {**chapter["data"], "text": text[start:end], "locator": {"type": "split", "chapter_id": chapter_id, "version": chapter["version"], "start": start, "end": end, "original": chapter["data"].get("locator")}}, parent_id=source["id"]))
    ids = source["data"]["chapter_ids"]
    index = ids.index(chapter_id)
    next_ids = ids[:index]+[p["id"] for p in pieces]+ids[index+1:]
    from .distillation.store import invalidate_current
    invalidate_current(source["id"])
    db.update(source["id"], data={"chapter_ids": next_ids, "chapter_versions": {cid: get(cid, "chapter")["version"] for cid in next_ids}})
    return pieces


@router.post("/sources/{source_id}/distill")
async def start_distill(source_id: str, body: dict):
    get(source_id, "source")
    validate_sources([source_id])
    chapters = chapters_for(source_id)
    ids = body.get("chapter_ids") or [c["id"] for c in chapters if c["data"].get("selected", True)]
    if not ids or set(ids) - {c["id"] for c in chapters}:
        raise ValueError("请选择属于当前资料版本的有效章节。")
    selected = [c for c in chapters if c["id"] in ids]
    if any(not c["data"].get("text", "").strip() for c in selected):
        raise ValueError("包含无文字章节，请先 OCR 或排除这些章节。")
    count = sum(len(re.sub(r"\s", "", c["data"].get("text", ""))) for c in selected)
    if count > int(settings().get("max_distill_characters", 500000)):
        raise ValueError("所选内容超过单次蒸馏上限，请减少章节；不会静默截断。")
    from .distillation.registry import get_method
    method = get_method(body.get("method_id", "basic"))
    if "prompt" in body and "focus" in body and body["prompt"] != body["focus"]:
        raise ValueError("prompt 与 focus 不能填写不同内容。")
    prompt = body.get("prompt", body.get("focus", ""))
    if not isinstance(prompt, str) or len(prompt) > 5000:
        raise ValueError("蒸馏提示词最多 5000 字。")
    profile = await ensure_model("distill", body.get("model_profile_id"))
    profiles = await proxy("GET", "/profiles")
    pinned = {p["id"]: p["version"] for p in profiles}
    job = enqueue("distill", {"source_id": source_id, "source_version": get(source_id,"source")["version"],
        "chapter_ids": ids, "chapter_versions": {c["id"]: c["version"] for c in selected},
        "focus": prompt, "prompt": prompt, "method_id": method.id, "method_snapshot": method.manifest(),
        "result_schema_version": 1, "model_profile_id": profile}, body.get("request_id"), profile_snapshots=pinned)
    if not job["data"].get("profile_snapshots"):
        job = db.update(job["id"], data={"profile_snapshots": pinned, "method_name": method.name})
    return job


@router.post("/sources/{source_id}/ocr")
async def start_ocr(source_id: str, body: dict):
    source = get(source_id, "source")
    validate_sources([source_id])
    if source["data"].get("format") != "pdf":
        raise ValueError("OCR 当前支持扫描 PDF。")
    chapters = chapters_for(source_id)
    selected = body.get("chapter_ids") or [c["id"] for c in chapters if c["data"].get("needs_ocr")]
    if not selected or set(selected)-{c["id"] for c in chapters}:
        raise ValueError("请选择当前资料中需要识别的有效 PDF 页面。")
    profile = await ensure_model("ocr", body.get("model_profile_id"))
    return enqueue("ocr", {"source_id": source_id, "chapter_ids": selected, "model_profile_id": profile}, body.get("request_id"))


@router.get("/cards")
def cards(source_id: str | None = None):
    return [c for c in db.list("card") if source_id is None or source_id in source_ids(c["data"])]


@router.post("/cards")
def create_card(body: dict):
    data = {"type": "claim", "source_ids": [], "chapter_ids": [], "references": [], "attribution": "用户补充", "review_status": "verified", "edit_origin": "user", **body.get("data", {})}
    if not str(data.get("content", "")).strip():
        raise ValueError("知识卡内容不能为空。")
    result = db.create("card", title(body.get("title")), validate_card_data(data))
    mark_knowledge_change(result["data"].get("source_ids", []), result["id"])
    return result


def mark_knowledge_change(ids, card_id):
    for sid in ids:
        if db.get(sid, "source"):
            db.update(sid, data={"latest_knowledge_change": {"card_id": card_id, "time": datetime.now(timezone.utc).isoformat()}})


def validate_card_data(data, previous=None):
    data = {**(previous or {}), **data}
    if not str(data.get("content", "")).strip():
        raise ValueError("知识卡内容不能为空。")
    if data.get("type", "claim") not in {"concept", "claim", "method", "boundary", "example", "fact"}:
        raise ValueError("知识卡类型无效。")
    sources = list(dict.fromkeys(data.get("source_ids", [])))
    for sid in sources:
        if not db.get(sid, "source"):
            raise ValueError("知识卡来源不存在或已删除。")
    refs = []
    for ref in data.get("references", []):
        if not isinstance(ref, dict):
            raise ValueError("引用结构无效。")
        old_ref = previous and ref in previous.get("references", [])
        source = db.get(ref.get("source_id", ""), "source")
        chapter = db.revision(ref.get("chapter_id", ""), int(ref.get("chapter_version", 0)))
        if not source or source["status"] in {"file_deleted", "deleting"} or not chapter or not chapter["data"].get("text"):
            if old_ref:
                refs.append(ref)
                continue
            raise ValueError("新引用需要可访问的原始来源和章节版本。")
        if chapter["data"].get("source_id") != source["id"]:
            raise ValueError("引用章节不属于指定来源。")
        version = db.revision(source["id"], int(ref.get("source_version", source["version"])))
        if not version or (version["data"].get("chapter_ids") and chapter["id"] not in version["data"]["chapter_ids"]):
            raise ValueError("引用章节不属于指定资料版本。")
        start, end = ref.get("start"), ref.get("end")
        text = chapter["data"]["text"]
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(text):
            raise ValueError("引用范围超出原文。")
        quote = text[start:end]
        if "quote" in ref and ref["quote"] != quote:
            raise ValueError("引用摘录与原文位置不一致，请重新核对。")
        refs.append({**ref, "source_version": version["version"], "quote": quote,
                     "label": f"{version['title']} · {chapter['title']}", "locator": chapter["data"].get("locator")})
        if source["id"] not in sources:
            sources.append(source["id"])
    return {**data, "source_ids": sources, "references": refs}


@router.get("/cards/{card_id}")
def card_detail(card_id: str):
    return {**get(card_id, "card"), "revisions": db.revisions(card_id)}


@router.patch("/cards/{card_id}")
def edit_card(card_id: str, body: dict):
    previous = get(card_id, "card")
    data = validate_card_data(body.get("data", {}), previous["data"])
    result = db.update(card_id, title=title(body["title"]) if "title" in body else None, data={**data, "edit_origin": "user_modified"})
    mark_knowledge_change(source_ids(previous["data"]) | source_ids(result["data"]), card_id)
    return result


@router.delete("/cards/{card_id}")
def delete_card(card_id: str):
    get(card_id, "card")
    result = db.delete(card_id)
    for kind in ("skill", "relation", "memory", "run"):
        for item in db.list(kind):
            data = item["data"]
            if card_id in data.get("card_ids", []) or card_id in {data.get("from_id"), data.get("to_id")}:
                db.update(item["id"], status="disabled", data={"disabled_reason": "依赖的知识卡已删除", "missing_card_ids": [card_id]})
    mark_knowledge_change([], card_id)
    return result


@router.post("/cards/{card_id}/restore")
def restore_card(card_id: str, body: dict):
    get(card_id, "card")
    previous = db.revision(card_id, int(body["version"]))
    if not previous:
        raise HTTPException(404, "历史版本不存在。")
    result = db.update(card_id, data={**previous["data"], "edit_origin": "user_restored"}, title=previous["title"], replace_data=True)
    mark_knowledge_change(source_ids(result["data"]), card_id)
    return result


@router.get("/evidence")
def evidence(source_id: str, chapter_id: str, chapter_version: int, start: int, end: int, source_version: int | None = None):
    source = db.get(source_id, "source")
    if not source or source["status"] in {"file_deleted", "deleting"}:
        return {"status": "missing", "detail": "原始来源已删除或不再可访问；保留摘录不代表能够重新核对原文。"}
    if source_version is not None:
        source = db.revision(source_id, source_version)
        if source is None:
            return {"status": "missing", "detail": "原来源版本不可访问，不能替换为其他版本。"}
    chapter = db.revision(chapter_id, chapter_version)
    if not chapter or chapter["data"].get("source_id") != source_id:
        return {"status": "missing", "detail": "此引用版本已不可访问。"}
    text = chapter["data"].get("text", "")
    if not 0 <= start < end <= len(text):
        raise ValueError("引用位置不在原文中。")
    return {"status": "available", "source": {"id": source_id, "title": source["title"]}, "chapter": chapter,
            "quote": text[start:end], "start": start, "end": end}


@router.get("/agents")
def agents():
    return db.list("agent")


@router.post("/agents")
def add_agent(body: dict):
    return db.create("agent", title(body.get("title"), 30), agent_data(body.get("data", {})), status=body.get("status", "available"))


@router.post("/agents/generate")
async def start_agents(body: dict):
    count = int(body.get("count", 1))
    if not 1 <= count <= 3:
        raise ValueError("一次生成 1–3 个 Agent 草稿。")
    binding = agent_data(body)
    profile = await ensure_model("agent", body.get("model_profile_id"))
    return enqueue("agent_generate", {**binding, "count": count, "model_profile_id": profile}, body.get("request_id"))


@router.get("/agents/{agent_id}")
def agent_detail(agent_id: str):
    agent = get(agent_id, "agent")
    return {"agent": agent, "revisions": db.revisions(agent_id), "knowledge_summary": knowledge_summary(agent)}


@router.patch("/agents/{agent_id}")
def edit_agent(agent_id: str, body: dict):
    agent = get(agent_id, "agent")
    return db.update(agent_id, data=agent_data(body.get("data", {}), agent["data"]), title=title(body["title"], 30) if "title" in body else None, status=body.get("status"))


@router.post("/agents/{agent_id}/copy")
def copy_agent(agent_id: str):
    agent = get(agent_id, "agent")
    return db.create("agent", (agent["title"][:26]+" 副本"), agent["data"], status="available")


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str):
    get(agent_id, "agent")
    related = {c["id"] for c in db.list("conversation") if agent_id in c["data"].get("agent_ids", [])}
    if any(j["status"] in ACTIVE and j["data"].get("input", {}).get("conversation_id") in related for j in db.list("job")):
        raise HTTPException(409, "此成员关联未结束任务，请先结束任务。")
    return db.delete(agent_id)


@router.get("/conversations")
def conversations():
    return db.list("conversation")


@router.post("/conversations")
def add_conversation(body: dict):
    data = body.get("data", {})
    ids = list(dict.fromkeys(data.get("agent_ids", [])))
    mode = data.get("mode", "single")
    if mode == "single" and len(ids) != 1 or mode == "group" and not 2 <= len(ids) <= 6:
        raise ValueError("单聊需一位成员，群聊需 2–6 位成员。")
    if mode not in {"single", "group"}:
        raise ValueError("会话类型无效。")
    if len(data.get("background", "")) > 5000:
        raise ValueError("会话背景最多 5000 字。")
    return db.create("conversation", title(body.get("title")), {**data, "agent_ids": ids, "agent_snapshots": snapshots(ids, allow_draft=bool(data.get("trial")))})


@router.get("/conversations/{conversation_id}")
def conversation_detail(conversation_id: str):
    return {"conversation": get(conversation_id, "conversation"), "messages": conversation_messages(conversation_id),
            "jobs": [j for j in db.list("job") if j["data"].get("input", {}).get("conversation_id") == conversation_id]}


def active_conversation_jobs(cid):
    return [j for j in db.list("job") if j["status"] in ACTIVE and j["data"].get("input", {}).get("conversation_id") == cid]


@router.patch("/conversations/{conversation_id}")
def edit_conversation(conversation_id: str, body: dict):
    get(conversation_id, "conversation")
    data = body.get("data", {})
    if {"agent_ids", "agent_snapshots", "mode"} & data.keys():
        raise ValueError("请使用成员或版本切换操作，不能静默修改会话身份。")
    if active_conversation_jobs(conversation_id) and data:
        raise HTTPException(409, "请先暂停并通过插话补充背景，或结束任务后修改设置。")
    if len(data.get("background", "")) > 5000:
        raise ValueError("会话背景最多 5000 字。")
    result = db.update(conversation_id, data=data, title=title(body["title"]) if "title" in body else None, status=body.get("status"))
    if {"shared_card_ids", "general_knowledge_overrides"} & data.keys():
        save_message(conversation_id, "会话知识策略变更", {"role": "system", "text": "用户调整了本会话共享知识或成员补充知识策略；仅影响之后的发言。"})
    return result


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    conversation = get(conversation_id, "conversation")
    if active_conversation_jobs(conversation_id):
        raise HTTPException(409, "请先结束当前任务再删除会话。")
    related_jobs = [j for j in db.list("job") if j["data"].get("input", {}).get("conversation_id") == conversation_id]
    db.update(conversation_id, status="deleting")
    for job in related_jobs:
        if not await purge_ai_requests(job):
            raise HTTPException(503, "独立 AI 服务副本尚未清理完毕。会话正在删除，请在服务恢复后重试。")
    for job in related_jobs:
        db.purge(job["id"])
    for message in conversation_messages(conversation_id):
        db.purge(message["id"])
    db.purge(conversation_id)
    purge_event_cache()
    return {"ok": True}


async def verify_conversation_models(conversation, ids):
    for aid in ids:
        agent = agent_in_conversation(conversation, aid)
        await ensure_model("chat", agent["data"].get("model_profile_id"))


@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: dict):
    conversation = get(conversation_id, "conversation")
    if conversation["status"] == "deleting":
        raise HTTPException(409, "会话正在删除，不能继续生成。")
    text = title(body.get("text"), 20000)
    ids = body.get("agent_ids") or conversation["data"]["agent_ids"]
    if not ids or set(ids) - set(conversation["data"]["agent_ids"]):
        raise ValueError("只能指定当前会话成员。")
    ids = [a for a in conversation["data"]["agent_ids"] if a in ids]
    await verify_conversation_models(conversation, ids)
    job = enqueue("chat", {"conversation_id": conversation_id, "agent_ids": ids, "text": text}, body.get("request_id"))
    if not any(m["data"].get("user_job_id") == job["id"] for m in conversation_messages(conversation_id)):
        save_message(conversation_id, "我", {"role": "user", "speaker_name": "我", "text": text, "user_job_id": job["id"], "source_ids": []})
    return job


@router.post("/conversations/{conversation_id}/discussions")
async def start_discussion(conversation_id: str, body: dict):
    conversation = get(conversation_id, "conversation")
    if conversation["status"] == "deleting":
        raise HTTPException(409, "会话正在删除，不能继续生成。")
    ids = conversation["data"]["agent_ids"]
    if len(ids) < 2:
        raise ValueError("自主讨论至少需要两位成员。")
    topic = title(body.get("topic"), 5000)
    if topic in {"随便聊聊", "聊聊", "随便"}:
        raise ValueError("请填写具体议题。")
    mode = body.get("mode", "ordered")
    goal = body.get("goal", "understand")
    if goal not in {"understand", "challenge_claim", "action_plan"}:
        raise ValueError("讨论目标无效。")
    rounds = int(body.get("rounds", 3))
    speeches = int(body.get("max_speeches", 9 if mode == "dynamic" else rounds*len(ids)))
    minutes = float(body.get("max_minutes", 20 if mode == "dynamic" else 30))
    if mode not in {"ordered", "challenge", "dynamic"} or not 1 <= rounds <= 10 or not 1 <= speeches <= 60 or not 1 <= minutes <= 180:
        raise ValueError("请检查讨论模式、1–10 轮、1–60 次发言和 1–180 分钟限制。")
    await verify_conversation_models(conversation, ids)
    if body.get("summary", True):
        await ensure_model("summary")
    job = enqueue("discussion", {"conversation_id": conversation_id, "agent_ids": ids, "topic": topic,
        "mode": mode, "goal": goal, "rounds": rounds, "max_speeches": speeches, "max_minutes": minutes, "summary": bool(body.get("summary", True)),
        "background": body.get("background", conversation["data"].get("background", ""))}, body.get("request_id"))
    if not any(m["data"].get("user_job_id") == job["id"] for m in conversation_messages(conversation_id)):
        if "background" in body:
            db.update(conversation_id, data={"background": body["background"]})
        save_message(conversation_id, "讨论议题", {"role": "user", "text": topic, "user_job_id": job["id"], "speaker_name": "我"})
    return job


@router.post("/conversations/{conversation_id}/interject")
def interject(conversation_id: str, body: dict):
    get(conversation_id, "conversation")
    text = title(body.get("text"), 5000)
    jobs = active_conversation_jobs(conversation_id)
    if not jobs:
        return save_message(conversation_id, "我", {"role": "user", "text": text, "speaker_name": "我"})
    job = jobs[0]
    if job["status"] in {"running", "pause_requested"}:
        return db.update(job["id"], status="pause_requested", data={"pending_interjection": text, "stage": "当前发言完成后暂停并插入"})
    if job["status"] in {"paused", "waiting_error", "interrupted"}:
        return save_message(conversation_id, "我", {"role": "user", "text": text, "speaker_name": "我", "interjection": True})
    raise ValueError("请等待任务开始或结束后插话。")


@router.post("/conversations/{conversation_id}/members")
def change_members(conversation_id: str, body: dict):
    conversation = get(conversation_id, "conversation")
    if active_conversation_jobs(conversation_id):
        raise HTTPException(409, "请结束现有任务后修改成员，包括已暂停任务。")
    ids = list(dict.fromkeys(body.get("agent_ids", [])))
    if not 2 <= len(ids) <= 6:
        raise ValueError("群聊需要 2–6 个成员。")
    existing = conversation["data"]["agent_snapshots"]
    snap = {aid: existing[aid] if aid in existing else snapshots([aid])[aid] for aid in ids}
    result = db.update(conversation_id, data={"agent_ids": ids, "agent_snapshots": snap, "mode": "group"})
    save_message(conversation_id, "成员变更", {"role": "system", "text": "本会话成员已由用户调整。", "agent_ids": ids})
    return result


@router.post("/conversations/{conversation_id}/switch-version")
def switch_version(conversation_id: str, body: dict):
    conversation = get(conversation_id, "conversation")
    if active_conversation_jobs(conversation_id):
        raise HTTPException(409, "请先结束任务再切换版本。")
    aid = body.get("agent_id")
    if aid not in conversation["data"]["agent_ids"]:
        raise ValueError("此 Agent 不属于当前会话。")
    agent = db.revision(aid, int(body["version"]))
    if not agent or not knowledge_summary(agent)["available"]:
        raise ValueError("目标版本不存在或知识已失效。")
    snap = conversation["data"]["agent_snapshots"]
    snap[aid] = {"version": agent["version"], "title": agent["title"]}
    result = db.update(conversation_id, data={"agent_snapshots": snap})
    save_message(conversation_id, "版本切换", {"role": "system", "text": f"用户将 {agent['title']} 切换到版本 {agent['version']}；此前发言和引用保持原记录。", "agent_id": aid})
    return result


@router.post("/conversations/{conversation_id}/summary")
async def start_summary(conversation_id: str, body: dict):
    get(conversation_id, "conversation")
    profile = await ensure_model("summary")
    return enqueue("summary", {"conversation_id": conversation_id, "model_profile_id": profile}, body.get("request_id"))


@router.post("/messages/{message_id}/feedback")
def feedback(message_id: str, body: dict):
    get(message_id, "message")
    if body.get("type") not in {"helpful", "source_mismatch", "misattribution", "off_topic", "有帮助", "来源不符", "错误归因", "没有回答问题"}:
        raise ValueError("反馈类型无效。")
    return db.update(message_id, data={"feedback": body["type"]})


@router.post("/messages/{message_id}/favorite")
def favorite(message_id: str, body: dict):
    get(message_id, "message")
    return db.update(message_id, data={"favorite": bool(body.get("favorite"))})


@router.get("/jobs")
def jobs():
    return db.list("job")


@router.get("/jobs/{job_id}")
def job_detail(job_id: str):
    return get(job_id, "job")


@router.post("/jobs/{job_id}/{action}")
async def control_job(job_id: str, action: str):
    job = get(job_id, "job")
    status = job["status"]
    if action == "pause":
        if job["data"]["kind"] not in {"discussion", "distill"} or status not in {"queued", "running"}:
            raise ValueError("只有待运行或运行中的讨论、蒸馏可以暂停。")
        job = db.update(job_id, status="paused" if status == "queued" else "pause_requested", data={"stage": "当前模型调用完成后暂停"})
    elif action == "cancel":
        if status not in ACTIVE:
            raise ValueError("此任务已结束。")
        job = db.update(job_id, status="cancelled", data={"stage": "已取消；成功部分保留"})
        await purge_ai_requests(job)
    elif action in {"resume", "retry"}:
        allowed = {"paused", "interrupted", "waiting_error", "partial", "failed"}
        if status not in allowed:
            raise ValueError("当前任务不可恢复或重试。")
        # A repeated model request is always a new explicit attempt, while successful step results remain reusable.
        job = db.update(job_id, status="queued", data={"attempt": job["data"].get("attempt", 0)+1,
            "stage": "等待恢复", "error": None})
    elif action == "skip":
        if job["data"]["kind"] != "discussion" or status != "waiting_error":
            raise ValueError("仅异常讨论允许跳过当前成员。")
        failed_step = job["data"].get("failed_step", "")
        if failed_step and not failed_step.startswith("discussion:"):
            raise ValueError("此异常不属于成员发言，不能跳过成员；请重试或结束。")
        aid = job["data"].get("current_agent_id")
        if not aid:
            raise ValueError("此异常不是成员发言失败，不能跳过。")
        skipped = list(set(job["data"].get("skipped_agents", [])) | {aid})
        remaining = set(job["data"]["input"]["agent_ids"]) - set(skipped)
        if len(remaining) < 2:
            raise ValueError("跳过后有效成员不足两位，请结束讨论或改为单聊。")
        job = db.update(job_id, status="queued", data={"skipped_agents": skipped, "position": job["data"].get("position", 0)+1,
            "attempt": job["data"].get("attempt", 0)+1, "stage": "已跳过该成员后续发言"})
    else:
        raise HTTPException(404, "未知任务操作。")
    emit_job(job)
    return job


@router.get("/events")
async def events(request: Request, topic: str = "jobs", after: int = 0):
    if topic != "jobs" and not (topic.startswith("job:") or topic.startswith("conversation:")):
        raise ValueError("事件主题无效。")
    async def stream():
        cursor = max(after, int(request.headers.get("last-event-id", "0") or 0))
        while not await request.is_disconnected():
            items = db.events(topic, cursor)
            for event in items:
                cursor = event["id"]
                yield f"id: {cursor}\nevent: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
            if not items:
                yield ": keepalive\n\n"
            await asyncio.sleep(.5)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/search")
def search(q: str, kind: str | None = None):
    allowed = {"source", "card", "agent", "conversation", "artifact", "skill"}
    if kind and kind not in allowed:
        raise ValueError("搜索类型无效。")
    return [r for r in db.search(q, kind) if r["kind"] in allowed]


app.include_router(router)
from .enhancements import router as extra_router
app.include_router(extra_router, prefix="/api/v1")

from .distillation.api import router as distillation_router
app.include_router(distillation_router, prefix="/api/v1")
