"""Version-pinned, resumable book distillation with a common result contract."""

from __future__ import annotations

import hashlib
import json
import uuid

from ..db import db
from ..domain import (
    CARD_SCHEMA,
    DISTILL_SCHEMA,
    STR,
    STRINGS,
    UNTRUSTED,
    card_valid_references,
    chapters_for,
    dedupe_references,
    json_schema,
    reference,
    require,
    user_data,
)
from ..jobs import JobControl, StepFailure
from .registry import get_method

SECTION = json_schema({"title": STR, "content": STR, "card_ids": STRINGS})
DECISION = json_schema(
    {"card_id": STR, "verdict": {"type": "string", "enum": ["supported", "review", "reject"]}, "reason": STR}
)
TEST = json_schema(
    {"card_id": STR, "question": STR, "answer": STR, "passed": {"type": "boolean"}, "reason": STR}
)
REPORT = json_schema(
    {
        "sections": {"type": "array", "items": SECTION},
        "decisions": {"type": "array", "items": DECISION},
        "tests": {"type": "array", "items": TEST},
        "warnings": STRINGS,
    }
)
REPAIR = json_schema(
    {
        "repairs": {
            "type": "array",
            "items": json_schema(
                {
                    "card_id": STR,
                    "card": CARD_SCHEMA,
                    "verdict": {"type": "string", "enum": ["supported", "review", "reject"]},
                    "reason": STR,
                    "test": TEST,
                }
            ),
        },
        "warnings": STRINGS,
    }
)
INTEGRATION = json_schema(
    {
        "overview": STR,
        "relationships": {
            "type": "array",
            "items": json_schema(
                {
                    "from": STR,
                    "to": STR,
                    "type": {"type": "string", "enum": ["支持", "限制", "反驳", "应用", "相似"]},
                    "basis": STR,
                }
            ),
        },
        "limitations": STRINGS,
    }
)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def batches(items, limit=24000):
    group, size = [], 0
    for item in items:
        length = len(encoded(item))
        if length > limit:
            raise StepFailure("单项阶段产物过长，请核对后重试；不会静默截断。")
        if group and size + length > limit:
            yield group
            group, size = [], 0
        group.append(item)
        size += length
    if group:
        yield group


def chunks(text, size=10000, overlap=600):
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary > start:
                end = boundary + 1
        yield start, end, text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def result_id(job_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "mindchime:distillation:" + job_id))


def step_digest(ctx):
    return [
        {
            "key": key,
            **{k: value.get(k) for k in ("status", "usage", "profile_id", "profile_version", "request_id")},
        }
        for key, value in ctx.job["data"].get("steps", {}).items()
    ]


async def run(ctx, job):
    payload = job["data"]["input"]
    method = get_method(payload.get("method_id", "basic"))
    if method.distillation_type != "knowledge":
        raise StepFailure("思想蒸馏不能使用知识处理器")
    manifest = payload.get("method_snapshot") or method.manifest()
    if manifest != method.manifest():
        raise StepFailure("此任务的方法版本与当前代码不一致，保留已有结果；请使用原版本恢复或新建任务。")
    source = db.revision(payload["source_id"], payload["source_version"])
    if not source:
        raise StepFailure("原始资料版本不可用，不会改用当前版本。")
    chapters = []
    for cid in payload["chapter_ids"]:
        chapter = db.revision(cid, payload["chapter_versions"][cid])
        if not chapter or not db.get(cid):
            raise StepFailure("原始章节版本不可用。")
        chapters.append(chapter)
    rid = result_id(job["id"])
    if not db.get(rid):
        db.create(
            "distillation",
            source["title"] + " · " + method.name,
            {
                "schema_version": 1,
                "distillation_type": "knowledge", "source_id": source["id"],
                "source_ids": [source["id"]],
                "source_version": source["version"],
                "chapter_ids": payload["chapter_ids"],
                "chapter_versions": payload["chapter_versions"],
                "method_id": method.id,
                "method_version": method.version,
                "method": manifest,
                "prompt": payload.get("prompt", ""),
                "job_id": job["id"],
                "card_ids": [],
                "card_versions": {},
                "extensions": [],
                "external_sources": {"status": "not_executed", "reason": "只依据输入书籍"},
            },
            status="running",
            parent_id=source["id"],
            id=rid,
        )
    db.update(rid, status="running")
    db.update(job["id"], data={"distillation_id": rid, "method_name": method.name})
    failures, summaries, warnings = [], [], []
    stage_reports = []
    try:
        preparation = []
        for stage in (s for s in method.stages if s.mode == "prepare"):
            raw_items = [
                {"chapter": chapter["title"], "source_text": text}
                for chapter in chapters
                for _, _, text in chunks(chapter["data"].get("text", ""), 10000, 0)
            ]
            level, inputs = 0, raw_items
            while inputs:
                values = []
                for n, group in enumerate(batches(inputs)):
                    ctx.check_control()
                    ctx.progress(method.name + " · " + stage.title)
                    report = await ctx.generate(
                        f"{UNTRUSTED}\n{stage.instruction}\n报告简明保留结构和跨章边界，不补写未处理部分。decisions/tests 留空。",
                        purpose="distill",
                        schema=REPORT,
                        step_key=f"method:{method.id}:prepare:{stage.id}:{level}:{n}",
                        messages=user_data(
                            {"prompt": payload.get("prompt", ""), "title": source["title"], "inputs": group}
                        ),
                    )
                    values.append(report)
                if len(values) == 1:
                    preparation.append(values[0])
                    stage_reports.append(
                        {"stage_id": stage.id, "title": stage.title, "batch": 0, "report": values[0]}
                    )
                    break
                inputs = [{"report": value} for value in values]
                level += 1
                if level > 8:
                    raise StepFailure("整书理解未收敛，请缩小范围。")
        for chapter in chapters:
            cid = chapter["id"]
            text = chapter["data"].get("text", "")
            chapter_summaries = []
            for number, (start, end, chunk) in enumerate(chunks(text)):
                for stage in (s for s in method.stages if s.mode == "extract"):
                    ctx.check_control()
                    ctx.progress(method.name + " · " + stage.title, chapter_id=cid)
                    key = f"method:{method.id}:{cid}:{number}:{stage.id}"
                    try:
                        value = await ctx.generate(
                            f"{UNTRUSTED}\n{stage.instruction}\n"
                            "summary 简明保留论证与条件；每张卡 references.quote 必须逐字摘自 source_text。"
                            "不要因为用户提示词而省略反例和边界。相同内容只在适合的类型提取，不凑数。"
                            "严格返回 summary（字符串）、cards（数组）、warnings（字符串数组）。卡片 type 只允许 concept、claim、method、boundary、example、fact；"
                            "框架用 method，原则用 claim，不使用 framework/principle 等自定义类型。attribution 只允许 作者观点、书中转述、模型归纳。"
                            "每张卡必须有 title、type、content、attribution、applicability、limitations（均为字符串）以及 references（仅含 quote 的对象数组），不得增加字段。",
                            purpose="distill",
                            schema=DISTILL_SCHEMA,
                            step_key=key,
                            messages=user_data(
                                {
                                    "title": source["title"],
                                    "chapter": chapter["title"],
                                    "prompt": payload.get("prompt", ""),
                                    "book_understanding": preparation,
                                    "source_text": chunk,
                                }
                            ),
                        )
                        chapter_summaries.append(value["summary"])
                        warnings.extend(value.get("warnings", []))
                        for index, card in enumerate(value["cards"]):
                            card_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{job['id']}:{key}:{index}"))
                            if db.get(card_id):
                                continue
                            # A quote elsewhere in the chapter is not proof it came from this chunk.
                            card = {
                                **card,
                                "references": [
                                    r for r in card["references"] if r["quote"] and r["quote"] in chunk
                                ],
                            }
                            refs = dedupe_references(
                                [
                                    reference(
                                        chapter,
                                        source,
                                        start + chunk.find(ref["quote"]),
                                        start + chunk.find(ref["quote"]) + len(ref["quote"]),
                                    )
                                    for ref in card["references"]
                                ]
                            )
                            duplicate = next(
                                (
                                    c
                                    for c in db.list("card")
                                    if c["data"].get("distillation_id") == rid
                                    and c["title"] == card["title"]
                                    and c["data"].get("content") == card["content"]
                                ),
                                None,
                            )
                            if duplicate:
                                merged = {
                                    "references": dedupe_references(
                                        duplicate["data"].get("references", []) + refs
                                    ),
                                    "chapter_ids": list(
                                        dict.fromkeys(duplicate["data"].get("chapter_ids", []) + [cid])
                                    ),
                                }
                                if any(duplicate["data"].get(key) != value for key, value in merged.items()):
                                    db.update(duplicate["id"], data=merged)
                                continue
                            db.create(
                                "card",
                                card["title"],
                                {
                                    **card,
                                    "source_ids": [source["id"]],
                                    "chapter_ids": [cid],
                                    "references": refs,
                                    "review_status": "pending",
                                    "edit_origin": "ai",
                                    "distillation_id": rid,
                                    "distill_job_id": job["id"],
                                    "source_version": source["version"],
                                    "extractor": stage.id,
                                    "provenance_warning": "未定位到可靠原文引用" if not refs else "",
                                    "validation": "pending"
                                    if method.id in {"cangjie", "bolan"}
                                    else "source_located"
                                    if refs
                                    else "review",
                                },
                                status="active" if refs else "disabled",
                                id=card_id,
                            )
                    except JobControl:
                        raise
                    except Exception as exc:  # noqa: BLE001 — isolate provider/validation failures per durable stage
                        failures.append(
                            {"chapter_id": cid, "step": key, "reason": str(exc) or type(exc).__name__}
                        )
            if chapter_summaries:
                summaries.append(
                    {"chapter_id": cid, "title": chapter["title"], "summary": "\n\n".join(chapter_summaries)}
                )
        cards = [c for c in db.list("card") if c["data"].get("distillation_id") == rid]
        # Each report sees source context around references, not only earlier model summaries.
        material = []
        for chapter in summaries:
            for n, (_, _, text) in enumerate(chunks(chapter["summary"], 6000, 0)):
                material.append({"chapter_id": chapter["chapter_id"], "part": n, "summary": text})
        chapter_map = {c["id"]: c for c in chapters}
        for card in cards:
            contexts = []
            for ref in card["data"].get("references", []):
                text = chapter_map[ref["chapter_id"]]["data"]["text"]
                contexts.append(
                    {
                        "chapter_id": ref["chapter_id"],
                        "text": text[max(0, ref["start"] - 300) : ref["end"] + 300],
                    }
                )
            material.append(
                {
                    "card_id": card["id"],
                    "title": card["title"],
                    "content": card["data"].get("content"),
                    "applicability": card["data"].get("applicability"),
                    "limitations": card["data"].get("limitations"),
                    "references": card["data"].get("references", []),
                    "source_context": contexts,
                }
            )
        if not summaries:
            raise StepFailure("没有章节成功，请核对任务错误后恢复。")
        # Bounded groups include every item; cross-group integration then consumes every group summary.
        groups = list(batches(material))
        for stage in (s for s in method.stages if s.mode not in {"extract", "prepare"}):
            if failures:
                break  # Downstream stages must not cache conclusions from missing inputs.
            ctx.check_control()
            ctx.progress(method.name + " · " + stage.title)
            reports = []
            for number, group in enumerate(groups):
                key = f"method:{method.id}:{stage.id}:{number}"
                ids = {item["card_id"] for item in group if "card_id" in item}
                previous = [r for r in stage_reports if r.get("batch") == number]
                # Prior reports can grow; use a bounded hierarchy rather than trimming.
                inputs = [{"material": group}] + [
                    {"previous_stage": r["title"], "report": r["report"]} for r in previous
                ]
                for part, input_group in enumerate([inputs]):
                    try:
                        if len(encoded(input_group)) > 60000:
                            raise StepFailure("阶段上下文超过限制，请缩小范围；不会截断或漏掉前序报告。")
                        value = await ctx.generate(
                            f"{UNTRUSTED}\n{stage.instruction}\n"
                            "只使用给定 material 和前序报告。每节观点的 card_ids 必须填写支持它的已有编号，不能关联候选能力。报告简洁，避免重抄正文。"
                            + {
                                "report": '本阶段只返回 {"sections":[{"title":"标题","content":"Markdown 正文，表格也写在这个字符串中","card_ids":[]}],"decisions":[],"tests":[],"warnings":[]}。不得添加其他字段或将 content 写成对象。',
                                "audit": "逐卡返回 decisions，字段为 card_id、verdict（supported/review/reject）、reason。sections/tests/warnings 均为数组，不适用时用 []，不得为 null。",
                                "test": "逐卡返回 tests，字段为 card_id、question、answer、passed（布尔值）、reason。sections/decisions/warnings 均为数组，不适用时用 []。",
                                "repair": '只返回 {"repairs":[],"warnings":[]}；repairs 只包含需修复的已有卡、修复后的完整 card、verdict、reason 和 test，严格遵照输出结构。不修复则留空。',
                            }[stage.mode],
                            purpose="distill",
                            schema=REPAIR if stage.mode == "repair" else REPORT,
                            step_key=f"{key}:{part}:"
                            + hashlib.sha256(encoded(input_group).encode()).hexdigest()[:16],
                            messages=user_data({"prompt": payload.get("prompt", ""), "inputs": input_group}),
                        )
                        warnings.extend(value.get("warnings", []))
                        if stage.mode == "audit":
                            decisions = {d["card_id"]: d for d in value["decisions"] if d["card_id"] in ids}
                            for card_id in ids:
                                decision = decisions.get(
                                    card_id, {"verdict": "review", "reason": "审核未覆盖此卡"}
                                )
                                current = require(card_id, "card")
                                valid = decision["verdict"] == "supported" and bool(
                                    current["data"].get("references")
                                )
                                db.update(
                                    card_id,
                                    status="active" if valid else "disabled",
                                    data={"validation": decision["verdict"], "audit": decision},
                                )
                        if stage.mode == "test":
                            tests = {t["card_id"]: t for t in value["tests"] if t["card_id"] in ids}
                            for card_id in ids:
                                test = tests.get(card_id, {"passed": False, "reason": "测试未覆盖此卡"})
                                if not test["passed"]:
                                    db.update(
                                        card_id,
                                        status="disabled",
                                        data={"validation": "review", "pressure_test": test},
                                    )
                                else:
                                    db.update(card_id, data={"pressure_test": test})
                        if stage.mode == "repair":
                            for repair in value["repairs"]:
                                if repair["card_id"] not in ids:
                                    continue
                                current = require(repair["card_id"], "card")
                                if current["status"] != "disabled":
                                    continue
                                refs = dedupe_references(
                                    [
                                        ref
                                        for cid in current["data"]["chapter_ids"]
                                        for ref in card_valid_references(
                                            repair["card"], chapter_map[cid], source
                                        )
                                    ]
                                )
                                valid = (
                                    refs
                                    and repair["verdict"] == "supported"
                                    and repair["test"]["passed"]
                                    and repair["test"]["card_id"] == current["id"]
                                )
                                repaired = dict(repair["card"])
                                repaired.pop("title", None)
                                db.update(
                                    current["id"],
                                    title=repair["card"]["title"],
                                    data={
                                        **repaired,
                                        "references": refs,
                                        "validation": "supported" if valid else "review",
                                        "repair_report": repair,
                                        "pressure_test": repair["test"],
                                        "audit": {"verdict": repair["verdict"], "reason": repair["reason"]},
                                        "review_status": "pending",
                                        "provenance_warning": "" if refs else "未定位到可靠原文引用",
                                    },
                                    status="active" if valid else "disabled",
                                )
                        report = {
                            "stage_id": stage.id,
                            "title": stage.title,
                            "batch": number,
                            "report": value,
                        }
                        reports.append(report)
                    except JobControl:
                        raise
                    except Exception as exc:  # noqa: BLE001 — isolate provider/validation failures per durable stage
                        failures.append(
                            {
                                "stage": stage.id,
                                "step": f"{key}:{part}",
                                "reason": str(exc) or type(exc).__name__,
                            }
                        )
            stage_reports.extend(reports)
            db.update(rid, data={"extensions": stage_reports, "failures": failures})
        cards = [c for c in db.list("card") if c["data"].get("distillation_id") == rid]
        integration_inputs = [{"chapter": s["title"], "summary": s["summary"]} for s in summaries]
        integration_inputs += [
            {
                "card_id": c["id"],
                "title": c["title"],
                "content": c["data"].get("content"),
                "status": c["status"],
                "limitations": c["data"].get("limitations"),
            }
            for c in cards
        ]
        integration = {"overview": "", "relationships": [], "limitations": []}
        try:
            if failures:
                raise StepFailure("前序阶段未完成，跨章整合等待恢复。")
            level, items = 0, integration_inputs
            while True:
                grouped = list(batches(items))
                values = []
                for n, group in enumerate(grouped):
                    ctx.check_control()
                    ctx.progress(method.name + " · 跨章整合", completed=n, total=len(grouped))
                    value = await ctx.generate(
                        f"{UNTRUSTED}\n根据所有实际成功内容生成总览、关系和局限。"
                        "关系 from/to 必须是已有且可用的 card_id。明确区分原文观点和模型推论，不得补写未处理章节。"
                        "总览控制在约1500字内，保留跨章限定条件。",
                        purpose="distill",
                        schema=INTEGRATION,
                        step_key=f"method:{method.id}:integration:{level}:{n}:"
                        + hashlib.sha256(encoded(group).encode()).hexdigest()[:16],
                        messages=user_data({"prompt": payload.get("prompt", ""), "material": group}),
                    )
                    values.append(value)
                    integration["relationships"].extend(value["relationships"])
                    integration["limitations"].extend(value["limitations"])
                if len(values) == 1:
                    integration["overview"] = values[0]["overview"]
                    break
                items = [{"overview": v["overview"], "limitations": v["limitations"]} for v in values]
                level += 1
                if level > 8:
                    raise StepFailure("跨章整合未收敛，请缩小范围后新建任务。")
        except JobControl:
            raise
        except Exception as exc:  # noqa: BLE001 — isolate provider/validation failures per durable stage
            failures.append({"stage": "integration", "reason": str(exc) or type(exc).__name__})
        valid_ids = {c["id"] for c in cards if c["status"] == "active"}
        relations = [
            r
            for r in integration["relationships"]
            if r["from"] in valid_ids and r["to"] in valid_ids and r["from"] != r["to"]
        ]
        invalid = len(integration["relationships"]) - len(relations)
        if invalid:
            warnings.append(f"已排除 {invalid} 条无效或指向候选卡的关系")
        integration["relationships"] = list({encoded(r): r for r in relations}.values())
        coverage = {
            "selected": payload["chapter_ids"],
            "completed": [
                s["chapter_id"]
                for s in summaries
                if not any(f.get("chapter_id") == s["chapter_id"] for f in failures)
            ],
            "failures": failures,
            "omitted": [c["id"] for c in chapters_for(source["id"]) if c["id"] not in payload["chapter_ids"]],
            "job_id": job["id"],
        }
        ctx.check_control()
        db.update(
            rid,
            status="partial" if failures else "completed",
            data={
                "integration": integration,
                "chapter_summaries": summaries,
                "coverage": coverage,
                "card_ids": [c["id"] for c in cards],
                "card_versions": {c["id"]: c["version"] for c in cards},
                "references": dedupe_references([r for c in cards for r in c["data"].get("references", [])]),
                "extensions": stage_reports,
                "warnings": list(dict.fromkeys(warnings)),
                "failures": failures,
                "quality": {
                    "located_cards": sum(bool(c["data"].get("references")) for c in cards),
                    "candidate_cards": sum(c["status"] == "disabled" for c in cards),
                    "invalid_relations": invalid,
                    "notice": "引用存在性与模型语义评审分别记录；结果仍需人工核对。",
                },
                "model_calls": step_digest(ctx),
            },
        )
        return {
            "distillation_id": rid,
            "distillation_type": "knowledge", "source_id": source["id"],
            "coverage": coverage,
            "integration": integration,
            "partial": bool(failures),
            "method_id": method.id,
        }
    except BaseException:
        if db.get(rid) and db.get(rid)["status"] == "running":
            saved_cards = [c for c in db.list("card") if c["data"].get("distillation_id") == rid]
            db.update(
                rid,
                status="incomplete",
                data={
                    "failures": failures,
                    "extensions": stage_reports,
                    "chapter_summaries": summaries,
                    "coverage": {"selected": payload["chapter_ids"], "completed": [], "failures": failures},
                    "card_ids": [c["id"] for c in saved_cards],
                    "card_versions": {c["id"]: c["version"] for c in saved_cards},
                    "model_calls": step_digest(ctx),
                },
            )
        raise
