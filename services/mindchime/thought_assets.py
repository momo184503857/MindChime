"""Versioned cognitive binding, evidence validation and runtime selection."""

import copy

from fastapi import HTTPException

from .db import db
from .domain import dedupe_references, reference, tokens
from .extra.common import require
from .jobs import StepFailure


def thought_binding(data, previous=None):
    merged = {**(previous or {}), **data}
    pid = merged.get("cognitive_profile_id")
    if not pid:
        return {}
    live = require(pid, "cognitive_profile", usable=True)
    version = int(merged.get("cognitive_profile_version") or live["version"])
    profile = db.revision(pid, version)
    if not profile:
        raise HTTPException(422, "思想资产版本不存在")
    reviewed_profile(profile, strict=True)
    return {
        "cognitive_profile_id": pid,
        "cognitive_profile_version": version,
        "person_id": profile["data"]["person_id"],
    }


def checked_references(refs, chapter_map):
    valid = []
    for ref in refs if isinstance(refs, list) else []:
        chapter = chapter_map.get(ref.get("chapter_id"))
        quote = ref.get("quote")
        if not chapter or not isinstance(quote, str) or not quote.strip():
            continue
        start = chapter["data"].get("text", "").find(quote)
        if start < 0:
            continue
        source = db.revision(chapter["data"]["source_id"], chapter["_source_version"])
        if source:
            valid.append(reference(chapter, source, start, start + len(quote)))
    return dedupe_references(valid)


def rule_evidence_valid(rule):
    refs = rule.get("references", [])
    if not refs:
        return False
    for ref in refs:
        chapter = db.revision(ref.get("chapter_id", ""), ref.get("chapter_version", 0))
        if not chapter or not db.get(ref.get("source_id", ""), "source"):
            return False
        text = chapter["data"].get("text", "")
        start = ref.get("start", -1)
        end = ref.get("end", -1)
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(text)
            or text[start:end] != ref.get("quote")
        ):
            return False
    return True


def reviewed_profile(profile, strict=False):
    data = copy.deepcopy(profile["data"])
    data["rules"] = [
        r
        for r in data.get("rules", [])
        if r.get("review_status") == "verified" and r.get("structural_valid") and rule_evidence_valid(r)
    ]
    if strict and not data["rules"]:
        raise HTTPException(409, "思想画像尚无已人工确认且证据有效的规则")
    data.pop("raw_candidates", None)
    return data


def runtime_profile(agent, query=""):
    pid = agent["data"].get("cognitive_profile_id")
    if not pid:
        return None
    require(pid, "cognitive_profile", usable=True)
    profile = db.revision(pid, agent["data"]["cognitive_profile_version"])
    if not profile:
        raise StepFailure("绑定思想版本不可访问")
    data = reviewed_profile(profile, strict=True)
    words = tokens(query)
    ranked = sorted(
        data["rules"],
        key=lambda r: len(words & tokens(r.get("name", "") + r.get("trigger", "") + r.get("behavior", ""))),
        reverse=True,
    )
    selected = ranked[:8]
    for rule in data["rules"]:
        if rule["category"] in {"limits", "values", "analysis_protocol"} and rule not in selected:
            selected.append(rule)
    return {
        "id": pid,
        "version": profile["version"],
        "person_id": data["person_id"],
        "rules": selected,
        "missing_dimensions": data.get("missing_dimensions", []),
        "identity_notice": "基于资料提炼的 AI 思想模拟，不是人物本人或其真实意见",
    }
