from __future__ import annotations

import json
import uuid

import httpx
from fastapi import HTTPException

from ..db import db


async def preflight(purpose: str, profile_id: str | None = None) -> str:
    from ..jobs import AI_URL, ai_headers, settings

    config = settings()
    profile_id = (
        profile_id or config.get("purpose_profiles", {}).get(purpose) or config.get("default_profile_id")
    )
    if not profile_id:
        from ..access import is_admin
        raise HTTPException(409, "请先在模型设置中选择可用模型" if is_admin() else "服务模型尚未配置，请联系管理员")
    try:
        async with httpx.AsyncClient(
            base_url=AI_URL, headers=ai_headers(), trust_env=False, timeout=10
        ) as client:
            response = await client.get("/ai/v1/profiles")
            response.raise_for_status()
            model = next((p for p in response.json() if p["id"] == profile_id), None)
    except httpx.HTTPError as exc:
        raise HTTPException(503, "独立 AI 服务暂不可用，请检查服务状态") from exc
    if not model or not model.get("enabled") or not model.get("configured"):
        raise HTTPException(409, "所选模型未配置或已停用，请先完成模型设置")
    return profile_id


def require(id: str, kind: str | None = None, usable: bool = False) -> dict:
    item = db.get(id, kind)
    if not item:
        raise HTTPException(404, "内容不存在或已删除")
    if usable and item["status"] in {
        "disabled",
        "archived",
        "candidate",
        "failed",
        "draft",
        "deleting",
        "cleaning",
    }:
        raise HTTPException(409, "该内容当前不可使用，请先检查来源并修复")
    return item


def title(value: str | None, default: str = "", max_length: int = 100) -> str:
    value = (value or default).strip()
    if not value or len(value) > max_length:
        raise HTTPException(422, f"标题不能为空，且最多 {max_length} 字")
    return value


def dependencies(data: dict, *, cards_required: bool = False) -> list[dict]:
    cards = []
    for cid in data.get("card_ids", []):
        cards.append(require(cid, "card", usable=True))
    if cards_required and not cards:
        raise HTTPException(422, "请至少选择一张可用知识卡")
    source_ids = set(data.get("source_ids", []))
    source_ids.update(sid for card in cards for sid in card["data"].get("source_ids", []))
    for sid in source_ids:
        source = require(sid, "source")
        if source["status"] in {"disabled", "deleting", "cleaning", "failed"}:
            raise HTTPException(409, "来源正在清理或不可用")
    return cards


def snapshot_cards(card_ids: list[str]) -> tuple[list[dict], list[str]]:
    cards = dependencies({"card_ids": card_ids}, cards_required=True)
    source_ids = sorted({sid for card in cards for sid in card["data"].get("source_ids", [])})
    return cards, source_ids


def once(
    job_id: str, key: str, kind: str, name: str, data: dict, status: str = "active", parent_id=None
) -> dict:
    id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"mindchime:{job_id}:{key}"))
    return db.get(id, include_deleted=True) or db.create(
        kind, name, data, status=status, parent_id=parent_id, id=id
    )


def context_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def markdown_record(item: dict) -> str:
    data = item["data"]
    lines = [f"# {item['title']}", "", f"版本：{item['version']} · 状态：{item['status']}", ""]
    content = data.get("content") or data.get("description") or ""
    lines.append(str(content))
    labels = {"purpose": "用途", "perspective": "分析视角", "framework": "思考框架", "methods": "可用方法",
              "boundaries": "适用边界", "style": "表达风格", "inputs": "需要的输入", "completion_criteria": "完成标准",
              "source_ids": "绑定来源", "chapter_ids": "章节范围", "card_ids": "知识卡范围", "excluded_card_ids": "排除知识",
              "source_versions": "来源版本", "card_versions": "知识卡版本", "identity_notice": "身份说明"}
    for key, label in labels.items():
        if data.get(key):
            lines += ["", f"## {label}", "", context_text(data[key]) if isinstance(data[key], (list, dict)) else str(data[key])]
    if item["kind"] == "agent":
        lines += ["", "知识策略：" + ("允许一般知识补充（需单独标记）" if data.get("general_knowledge") else "仅绑定知识与用户输入")]
    if data.get("items"):
        lines += ["", "## 行动清单", ""]
        for action in data["items"]:
            lines += [f"- [{'x' if action.get('status') == 'completed' else ' '}] {action.get('text', '')}",
                      f"  日期：{action.get('due_date', '')}；结果：{action.get('result', '')}；复盘：{action.get('review_question', '')}"]
    if data.get("steps"):
        lines += ["", "## 实践步骤", ""]
        for i, step in enumerate(data["steps"], 1):
            lines += [
                f"### {i}. {step.get('title', '')}",
                "",
                step.get("instruction", ""),
                "",
                f"产物：{step.get('output', '')}",
                "",
            ]
    for field, label in [("applicability", "适用条件"), ("limitations", "边界"), ("reflection", "复盘")]:
        if data.get(field):
            lines += ["", f"## {label}", "", str(data[field])]
    references = data.get("references", [])
    if references:
        lines += ["", "## 来源", ""]
        for ref in references:
            lines.append(
                f"- {ref.get('label') or ref.get('source_id', '来源')}；位置：{ref.get('chapter_id', '')}"
            )
            if ref.get("quote"):
                lines.append(f"> {ref['quote']}")
    if data.get("edited") or data.get("edit_origin") == "user_modified":
        lines += ["", "用户已编辑。修改内容不自动视为原书主张。"]
    return "\n".join(lines).strip() + "\n"
