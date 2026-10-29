from copy import deepcopy

from sqlalchemy.exc import IntegrityError

from ..db import db
from .registry import get_method


def migrate_legacy():
    """Idempotent additive reconstruction, never invent missing historical output."""
    from .engine import result_id

    for job in db.list("job"):
        if job["data"].get("kind") != "distill" or job["data"].get("input", {}).get("result_schema_version"):
            continue
        if job["status"] not in {"completed", "partial"}:
            continue
        payload = job["data"].get("input", {})
        source = db.get(payload.get("source_id", ""), "source")
        rid = result_id(job["id"])
        if not source or db.get(rid):
            continue
        cards = [c for c in db.list("card") if c["data"].get("distill_job_id") == job["id"]]
        original = job["data"].get("result") or {}
        snapshot = next(
            (s for s in db.revisions(source["id"]) if s["data"].get("latest_distill_job_id") == job["id"]),
            None,
        )
        integration = original.get("integration") or (snapshot or {}).get("data", {}).get("distillation")
        coverage = original.get("coverage") or (snapshot or {}).get("data", {}).get("coverage")
        missing = [name for name, value in [("总览", integration), ("覆盖报告", coverage)] if not value]
        data = {
            "schema_version": 1,
            "legacy": True,
            "method_id": "basic",
            "method_version": "legacy-v1",
            "method": get_method("basic").manifest(),
            "source_id": source["id"],
            "source_ids": [source["id"]],
            "source_version": payload.get("source_version"),
            "chapter_ids": payload.get("chapter_ids", []),
            "chapter_versions": payload.get("chapter_versions", {}),
            "prompt": payload.get("focus", ""),
            "job_id": job["id"],
            "card_ids": [c["id"] for c in cards],
            "card_versions": {c["id"]: c["version"] for c in cards},
            "integration": integration or {},
            "coverage": coverage or {},
            "chapter_summaries": [],
            "extensions": [],
            "warnings": ["历史重建：只保留实际可恢复的资料，缺失字段不补造。"]
            + [f"历史{name}缺失" for name in missing],
            "external_sources": {"status": "not_executed"},
        }
        for key, step in job["data"].get("steps", {}).items():
            value = step.get("result", {}).get("json")
            if key.startswith("chapter:") and step.get("status") == "completed" and isinstance(value, dict):
                data["chapter_summaries"].append(
                    {"chapter_id": key.split(":")[1], "summary": value.get("summary", "")}
                )
        try:
            db.create(
                "distillation",
                source["title"] + " · 基础蒸馏（历史）",
                data,
                status="completed" if not missing and job["status"] == "completed" else "partial",
                parent_id=source["id"],
                id=rid,
            )
        except IntegrityError:
            continue
        # The formerly current result remains current only for existing legacy sources.
        if source["data"].get("latest_distill_job_id") == job["id"] and not source["data"].get(
            "distillation_selection_initialized"
        ):
            db.update(
                source["id"], data={"active_distillation_id": rid, "distillation_selection_initialized": True}
            )


def result_detail(id):
    result = db.get(id, "distillation")
    if not result:
        raise ValueError("蒸馏结果不存在或已删除。")
    data = deepcopy(result["data"])
    cards = []
    for cid in data.get("card_ids", []):
        if db.get(cid, "card") and (card := db.revision(cid, data.get("card_versions", {}).get(cid, 1))):
            cards.append(card)
    return {**result, "cards": cards}


def activate(id):
    from ..domain import require, validate_sources

    result = require(id, "distillation")
    if result["status"] != "completed":
        raise ValueError("只有完整成功的结果才能设为当前结果。")
    if any(not db.get(cid, "card") for cid in result["data"].get("card_ids", [])):
        raise ValueError("结果存在缺失知识卡，请修复依赖后再启用。")
    sid = result["data"]["source_id"]
    validate_sources([sid])
    source = require(sid, "source")
    if source["status"] == "file_deleted":
        raise ValueError("原文已删除，不能更换蒸馏结果。")
    if set(result["data"].get("chapter_ids", [])) - set(source["data"].get("chapter_ids", [])):
        raise ValueError("原文章节结构已变化，请重新蒸馏当前版本。")
    for cid, version in result["data"].get("chapter_versions", {}).items():
        live = require(cid, "chapter")
        old = db.revision(cid, version)
        if not old or old["data"].get("text") != live["data"].get("text"):
            raise ValueError("原文已变化，请重新蒸馏当前版本。")
    data = result["data"]
    db.update(
        sid,
        data={
            "active_distillation_id": id,
            "distillation_selection_initialized": True,
            "distillation": data.get("integration", {}),
            "coverage": data.get("coverage", {}),
            "latest_distill_job_id": data.get("job_id"),
        },
    )
    return result


def invalidate_current(source_id, chapter_id=None):
    """Raw edits invalidate only the default selection, never historical bindings."""
    source = db.get(source_id, "source")
    if not source:
        return
    rid = source["data"].get("active_distillation_id")
    result = db.get(rid, "distillation") if rid else None
    if not result or (chapter_id and chapter_id not in result["data"].get("chapter_ids", [])):
        return
    db.update(
        source_id,
        data={
            "active_distillation_id": None,
            "distillation_selection_initialized": True,
            "distillation": {},
            "coverage": {},
            "latest_distill_job_id": None,
            "distillation_notice": "原文或章节结构已变化，历史结果保留；请明确选择历史知识或重新蒸馏。",
        },
    )


def usable_sections(result, card_ids):
    """Only anchored sections wholly supported by selected, live usable cards enter generation."""
    allowed = {cid for cid in card_ids if (card := db.get(cid, "card")) and card["status"] != "disabled"}
    return [
        deepcopy(section)
        for extension in result["data"].get("extensions", [])
        for section in extension.get("report", {}).get("sections", [])
        if section.get("card_ids") and set(section["card_ids"]) <= allowed
    ]
