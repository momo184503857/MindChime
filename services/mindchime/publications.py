"""Explicit, immutable public snapshots. Publication never silently publishes dependencies."""

from __future__ import annotations

import copy

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from .access import PUBLIC_KINDS, UNAVAILABLE, identity, require_admin
from .db import Publication, PublishedRevision, db, now

router = APIRouter()
ROOT_KINDS = PUBLIC_KINDS - {"chapter"}


def all_publications(history=False):
    with Session(db.engine) as session:
        model = PublishedRevision if history else Publication
        current_ids = {p.record_id for p in session.query(Publication).all()}
        return [
            {
                "record_id": p.record_id,
                "version": p.version,
                "manifest": copy.deepcopy(p.manifest),
                "published_at": p.published_at,
            }
            for p in session.query(model).all()
            if p.record_id in current_ids
        ]


def usable(record):
    return record and record["status"] not in UNAVAILABLE


def visible_snapshot(id, version=None, _seen=None):
    seen = set(_seen or ())
    if id in seen:
        return None
    seen.add(id)
    with identity(None):
        live = db.get(id)
        if not live or live["status"] in {
            "deleted",
            "deleting",
            "disabled",
            "failed",
            "cleaning",
            "archived",
        }:
            return None
        for publication in sorted(
            all_publications(history=version is not None), key=lambda p: p["published_at"], reverse=True
        ):
            manifest = publication["manifest"]
            # Resolve only manifests which actually contain the requested snapshot.
            # Checking every unrelated root first recursively enumerates the entire graph.
            if not any(
                snapshot["id"] == id and (version is None or snapshot["version"] == version)
                for snapshot in manifest.get("snapshots", [])
            ):
                continue
            root = db.get(publication["record_id"])
            if not root or root["status"] in {
                "deleted",
                "deleting",
                "disabled",
                "failed",
                "cleaning",
                "archived",
            }:
                continue
            manifest = publication["manifest"]
            # Revoked/missing dependencies invalidate runtime availability, not personal history.
            if any(
                not visible_snapshot(dep["id"], dep.get("version"), seen)
                for dep in manifest.get("dependencies", [])
            ):
                continue
            for snapshot in manifest.get("snapshots", []):
                if snapshot["id"] == id and (version is None or snapshot["version"] == version):
                    value = copy.deepcopy(snapshot)
                    value["published_version"] = snapshot["version"]
                    if value["kind"] == "source":
                        rid = value["data"].get("active_distillation_id")
                        if rid and not any(p["record_id"] == rid for p in all_publications()):
                            value["data"].pop("active_distillation_id", None)
                    return value
    return None


def dependencies(item):
    data, kind = item["data"], item["kind"]
    result = []

    def add(id, version=None):
        if id and id != item["id"] and not any(d["id"] == id for d in result):
            result.append({"id": id, "version": version})

    if kind == "source":
        return result
    for sid in data.get("source_ids", []):
        add(sid, data.get("source_versions", {}).get(sid))
    if data.get("source_id"):
        add(data["source_id"], data.get("source_version"))
    if kind == "cognitive_profile":
        add(data.get("person_id"))
    if kind == "agent":
        add(data.get("person_id"))
        add(data.get("cognitive_profile_id"), data.get("cognitive_profile_version"))
        for rid in data.get("distillation_ids", {}).values():
            add(rid)
    if kind in {"skill", "agent"}:
        for cid in data.get("card_ids", []):
            add(cid, data.get("card_versions", {}).get(cid))
    if kind == "relation":
        add(data.get("from_id"))
        add(data.get("to_id"))
    return result


def build_manifest(item):
    if item["kind"] not in ROOT_KINDS:
        raise HTTPException(422, "此内容不支持发布")
    blockers = []
    if not usable(item):
        blockers.append("内容尚未启用、仍为候选或已失效")
    deps = dependencies(item)
    for dep in deps:
        public = visible_snapshot(dep["id"], dep.get("version"))
        if public:
            dep["version"] = public["version"]
        if not public:
            target = db.get(dep["id"])
            blockers.append(
                f"依赖尚未发布或版本不可用：{target['title'] if target else dep['id']}（{dep['id']}，版本 {dep.get('version') or '已发布版本'}）"
            )
    value = copy.deepcopy(item)
    value.pop("owner_user_id", None)
    snapshots = [value]
    if item["kind"] == "source":
        for cid in item["data"].get("chapter_ids", []):
            version = item["data"].get("chapter_versions", {}).get(cid)
            chapter = db.revision(cid, version) if version else db.get(cid)
            if chapter and usable(chapter):
                snapshots.append(chapter)
    if item["kind"] == "distillation":
        if item["status"] != "completed":
            blockers.append("蒸馏任务尚未完整完成")
        cards = []
        for cid in item["data"].get("card_ids", []):
            live = db.get(cid)
            v = item["data"].get("card_versions", {}).get(cid)
            card = db.revision(cid, v) if v else live
            if usable(live) and card and card_reviewed(card):
                card["data"]["review_status"] = "verified"
                cards.append(card)
        snapshots.extend(cards)
        value["data"]["card_ids"] = [c["id"] for c in cards]
        value["data"]["card_versions"] = {c["id"]: c["version"] for c in cards}
        # Process reports can include rejected candidates and are restricted to the administrator.
        for key in ("extensions", "stages", "stage_results", "reports", "candidates", "profile_snapshot"):
            value["data"].pop(key, None)
        if item["data"].get("distillation_type", "knowledge") == "thought":
            pid = item["data"].get("cognitive_profile_id")
            if not pid or not visible_snapshot(pid):
                blockers.append("请先审核并发布关联思想画像")
    if item["kind"] == "card" and not card_reviewed(item):
        blockers.append("知识卡需要人工核对后发布")
    if item["kind"] == "cognitive_profile":
        from .thought_assets import reviewed_profile

        value["data"] = reviewed_profile(item, strict=True)
    if item["kind"] == "relation" and item["data"].get("review_status") not in {
        "verified",
        "confirmed",
        "reviewed",
    }:
        blockers.append("关系需要人工确认")
    if blockers:
        raise HTTPException(409, {"message": "发布前请先处理依赖或审核", "blockers": blockers})
    return {"snapshots": snapshots, "dependencies": deps}


@router.get("/publications")
def list_publications():
    require_admin()
    pubs = {p["record_id"]: p for p in all_publications()}
    return [
        {
            **r,
            "published_version": pubs.get(r["id"], {}).get("version"),
            "published_at": pubs.get(r["id"], {}).get("published_at"),
        }
        for r in db.list()
        if r["kind"] in ROOT_KINDS
    ]


@router.get("/publications/{id}/preview")
def preview(id: str, version: int | None = None):
    require_admin()
    item = db.get(id)
    if item and version is not None:
        item = db.revision(id, version)
    if not item:
        raise HTTPException(404, "资产不存在")
    try:
        manifest = build_manifest(item)
        return {"ready": True, "dependencies": manifest["dependencies"], "blockers": []}
    except HTTPException as exc:
        return {
            "ready": False,
            "blockers": exc.detail.get("blockers", [exc.detail.get("message")])
            if isinstance(exc.detail, dict)
            else [str(exc.detail)],
        }


@router.post("/publications/{id}")
def publish(id: str, version: int | None = None):
    require_admin()
    item = db.get(id)
    if item and version is not None:
        item = db.revision(id, version)
    if not item:
        raise HTTPException(404, "资产不存在")
    manifest = build_manifest(item)
    with Session(db.engine) as session, session.begin():
        existing = session.get(Publication, id)
        if existing:
            existing.version = item["version"]
            existing.manifest = manifest
            existing.published_at = now()
        else:
            session.add(
                Publication(record_id=id, version=item["version"], manifest=manifest, published_at=now())
            )
        historic = session.get(PublishedRevision, (id, item["version"]))
        if not historic:
            session.add(
                PublishedRevision(
                    record_id=id, version=item["version"], manifest=manifest, published_at=now()
                )
            )
    return {"record_id": id, "published_version": item["version"]}


@router.delete("/publications/{id}")
def unpublish(id: str):
    require_admin()
    with Session(db.engine) as session, session.begin():
        value = session.get(Publication, id)
        if value:
            session.delete(value)
    return {"unpublished": True}


@router.get("/publications/{id}/versions")
def publishable_versions(id: str):
    require_admin()
    if not db.get(id):
        raise HTTPException(404, "资产不存在")
    return [r["version"] for r in db.revisions(id)]


@router.get("/publications/{id}/version-detail")
def version_detail(id: str, version: int):
    require_admin()
    item = db.revision(id, version)
    if not item:
        raise HTTPException(404, "版本不存在")
    return item


def card_reviewed(card):
    from .auth import connection

    with connection() as conn:
        row = conn.execute(
            "SELECT decision FROM asset_reviews WHERE record_id=? AND version=?",
            (card["id"], card["version"]),
        ).fetchone()
    if row:
        return row[0] == "verified"
    return card["data"].get("review_status") in {"verified", "reviewed"}


@router.post("/reviews/{id}")
def review_version(id: str, body: dict):
    require_admin()
    version = int(body.get("version", 0))
    item = db.revision(id, version)
    if not item or item["kind"] != "card":
        raise HTTPException(422, "请选择明确的知识卡版本")
    if not usable(db.get(id)):
        raise HTTPException(409, "失效或候选知识卡不能确认，请先修复来源")
    from .main import validate_card_data

    validate_card_data(item["data"])
    decision = body.get("decision", "verified")
    if decision not in {"verified", "rejected"}:
        raise HTTPException(422, "审核结论无效")
    from .access import current
    from .auth import connection

    with connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO asset_reviews VALUES (?,?,?,?,?,?)",
            (
                id,
                version,
                decision,
                str(body.get("note", ""))[:2000],
                (current() or {}).get("id", "local-admin"),
                now(),
            ),
        )
    return {"record_id": id, "version": version, "decision": decision}


def purge_cached_record(id):
    for model in (Publication, PublishedRevision):
        with Session(db.engine) as session, session.begin():
            for item in session.query(model).all():
                if item.record_id == id or any(s["id"] == id for s in item.manifest.get("snapshots", [])):
                    session.delete(item)


def clean_source_cache(source_id, derived):
    for model in (Publication, PublishedRevision):
        with Session(db.engine) as session, session.begin():
            for item in session.query(model).all():
                manifest = copy.deepcopy(item.manifest)
                affected = any(
                    s["id"] == source_id
                    or s.get("data", {}).get("source_id") == source_id
                    or source_id in s.get("data", {}).get("source_ids", [])
                    for s in manifest.get("snapshots", [])
                )
                if derived and affected:
                    session.delete(item)
                    continue
                if not derived:
                    for snapshot in manifest.get("snapshots", []):
                        if snapshot["id"] == source_id:
                            snapshot["data"]["file_path"] = None
                            snapshot["data"]["original_available"] = False
                            snapshot["status"] = "file_deleted"
                        if snapshot["kind"] == "chapter" and snapshot["data"].get("source_id") == source_id:
                            snapshot["data"].pop("text", None)
                            snapshot["status"] = "file_deleted"
                    item.manifest = manifest
