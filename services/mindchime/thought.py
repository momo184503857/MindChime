"""Person management and independent thought-distillation API."""

import copy

from fastapi import APIRouter, HTTPException

from .access import require_admin
from .db import db, now
from .domain import chapters_for
from .extra.common import preflight, require, title
from .jobs import enqueue, register_handler
from .thought_assets import reviewed_profile, rule_evidence_valid
from .thought_engine import run

router = APIRouter()


@router.get("/persons")
def persons():
    return db.list("person")


@router.post("/persons")
def create_person(body: dict):
    require_admin()
    return db.create(
        "person",
        title(body.get("title")),
        {"description": str(body.get("data", {}).get("description", ""))[:5000]},
    )


@router.patch("/persons/{id}")
def edit_person(id: str, body: dict):
    require_admin()
    require(id, "person")
    return db.update(
        id,
        title=title(body["title"]) if "title" in body else None,
        data={"description": str(body.get("data", {}).get("description", ""))[:5000]},
    )


@router.delete("/persons/{id}")
def delete_person(id: str):
    require_admin()
    require(id, "person")
    if any(p["data"].get("person_id") == id for p in db.list("cognitive_profile")):
        raise HTTPException(409, "人物仍有关联思想资产，请先归档资产")
    return db.delete(id)


@router.get("/cognitive-profiles")
def profiles(person_id: str | None = None):
    return [
        p for p in db.list("cognitive_profile") if not person_id or p["data"].get("person_id") == person_id
    ]


@router.get("/cognitive-profiles/{id}")
def profile_detail(id: str, version: int | None = None):
    require(id, "cognitive_profile")
    item = db.revision(id, version) if version else db.get(id)
    if not item:
        raise HTTPException(404, "思想版本不可访问")
    return {**item, "revisions": db.revisions(id)}


@router.patch("/cognitive-profiles/{id}")
def edit_profile(id: str, body: dict):
    require_admin()
    item = require(id, "cognitive_profile")
    # Human review can accept/reject rules, but cannot turn invented evidence into valid citations.
    decisions = {r["id"]: r for r in body.get("rules", []) if isinstance(r, dict) and r.get("id")}
    rules = copy.deepcopy(item["data"].get("rules", []))
    for rule in rules:
        decision = decisions.get(rule["id"])
        if not decision:
            continue
        status = decision.get("review_status", rule["review_status"])
        if status not in {"verified", "rejected", "pending_review", "candidate"}:
            raise HTTPException(422, "审核状态无效")
        if status == "verified" and (not rule.get("structural_valid") or not rule_evidence_valid(rule)):
            raise HTTPException(422, "证据无效的规则不能确认，请补充资料后重新蒸馏")
        rule["review_status"] = status
        rule["review_note"] = str(decision.get("review_note", ""))[:2000]
        rule["reviewed_at"] = now()
    state = body.get("status", item["status"])
    if state not in {"active", "draft", "archived", "disabled"}:
        raise HTTPException(422, "思想资产状态无效")
    if state == "active":
        reviewed_profile({**item, "data": {**item["data"], "rules": rules}}, strict=True)
    return db.update(
        id, data={"rules": rules}, status=state, title=title(body["title"]) if body.get("title") else None
    )


@router.get("/research/config")
async def research_config():
    require_admin()
    from .main import proxy

    return await proxy("GET", "/research/config")


@router.patch("/research/config")
async def configure_research(body: dict):
    require_admin()
    from .main import proxy

    return await proxy("PATCH", "/research/config", body)


@router.post("/distillations")
async def start_distillation(body: dict):
    require_admin()
    kind = body.get("distillation_type", "knowledge")
    ids = list(dict.fromkeys(body.get("source_ids", [])))
    if kind == "knowledge":
        if len(ids) != 1 or body.get("allow_network", False):
            raise HTTPException(422, "知识蒸馏请选择一份本地资料，并关闭联网")
        from .main import start_distill

        return await start_distill(ids[0], body)
    if kind != "thought" or body.get("method_id", "nuwa") != "nuwa":
        raise HTTPException(422, "思想蒸馏请选择女娲方法")
    person = require(body.get("person_id", ""), "person", usable=True)
    network = body.get("allow_network", False)
    if not isinstance(network, bool):
        raise HTTPException(422, "联网开关必须为布尔值")
    if not ids and not network:
        raise HTTPException(422, "关闭联网时，请至少选择一份资料")
    selected = set(body.get("chapter_ids", []))
    chapters = []
    versions = {}
    chapter_versions = {}
    for sid in ids:
        source = require(sid, "source", usable=True)
        versions[sid] = source["version"]
        for chapter in chapters_for(sid):
            if (
                (not selected or chapter["id"] in selected)
                and chapter["data"].get("selected", True)
                and chapter["data"].get("text", "").strip()
            ):
                chapters.append(chapter["id"])
                chapter_versions[chapter["id"]] = chapter["version"]
    if selected - set(chapters):
        raise HTTPException(422, "所选章节不属于可用资料范围")
    if ids and not chapters:
        raise HTTPException(422, "所选资料没有可分析的正文")
    from .jobs import settings

    total = sum(len(db.revision(cid, chapter_versions[cid])["data"].get("text", "")) for cid in chapters)
    if total > int(settings().get("max_distill_characters", 500000)):
        raise HTTPException(422, "思想蒸馏资料超过单次字符限制，请缩小范围")
    research = None
    if network:
        research = await research_config()
        if not research.get("configured") or not research.get("enabled"):
            raise HTTPException(409, "请先由管理员配置并启用搜索服务")
    model = await preflight("thought_distill", body.get("model_profile_id"))
    from .distillation.registry import get_method

    method = get_method("nuwa").manifest()
    from .main import proxy

    pinned = {p["id"]: p["version"] for p in await proxy("GET", "/profiles")}
    return enqueue(
        "thought_distill",
        {
            "distillation_type": "thought",
            "person_id": person["id"],
            "person_snapshot": person,
            "source_ids": ids,
            "source_versions": versions,
            "chapter_ids": chapters,
            "chapter_versions": chapter_versions,
            "prompt": str(body.get("prompt", ""))[:5000],
            "allow_network": network,
            "research_config_version": research["version"] if research else None,
            "research_limits": {"searches": 6, "results_per_search": 5, "pages": 20},
            "model_profile_id": model,
            "method_id": "nuwa",
            "method_snapshot": method,
        },
        body.get("request_id"),
        profile_snapshots=pinned,
    )


@router.post("/distillations/{id}/continue-local")
def continue_local(id: str):
    require_admin()
    result = require(id, "distillation")
    job = require(result["data"]["job_id"], "job")
    if job["data"].get("kind") != "thought_distill" or job["status"] not in {
        "waiting_error",
        "interrupted",
        "paused",
    }:
        raise HTTPException(409, "当前任务不支持跳过失败采集")
    db.update(
        job["id"],
        data={"accept_partial_research": True, "attempt": job["data"].get("attempt", 0) + 1},
        status="queued",
    )
    return {"job_id": job["id"], "status": "queued"}


def register():
    register_handler("thought_distill", run)
