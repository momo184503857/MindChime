from fastapi import APIRouter

from ..db import db
from .registry import methods
from .store import activate, result_detail

router = APIRouter()


@router.get("/distillation-methods")
def list_methods():
    return {"default_method_id": "cangjie", "methods": [m.manifest() for m in methods().values()]}


@router.get("/distillations")
def list_results(source_id: str):
    return db.list("distillation", parent_id=source_id)


@router.get("/distillations/{id}")
def detail(id: str):
    return result_detail(id)


@router.post("/distillations/{id}/activate")
def activate_result(id: str):
    return activate(id)


@router.post("/distillations/{id}/skills")
def skill_from_result(id: str, body: dict):
    """Explicit conversion; never activate generated practice code or scripts."""
    from ..extra.skills import validate_skill

    result = result_detail(id)
    if result["status"] != "completed":
        raise ValueError("请先完成此蒸馏。")
    data = body.get("data", {})
    card_ids = data.get("card_ids", [])
    allowed = {c["id"] for c in result["cards"] if (live := db.get(c["id"])) and live["status"] != "disabled"}
    if not card_ids or set(card_ids) - allowed:
        raise ValueError("请绑定本次结果中的可用知识卡。")
    data = {**data, "distillation_id": id, "source_ids": result["data"]["source_ids"]}
    validate_skill(data)
    title = str(body.get("title", "")).strip()
    if not title or len(title) > 100:
        raise ValueError("请填写 1–100 字的方法名称。")
    return db.create("skill", title, data)
