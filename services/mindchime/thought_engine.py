"""Resumable local/optional-network Nuwa production pipeline."""

import hashlib
import json

from fastapi import HTTPException

from .db import db, now
from .distillation.engine import batches, chunks, step_digest
from .domain import UNTRUSTED, chapters_for
from .extra.common import once, require
from .jobs import StepFailure
from .thought_assets import checked_references
from .thought_spec import ASSESS, DIMENSIONS, OBSERVATIONS, RULES, TESTS


async def research_step(ctx, key, operation, body):
    from .main import proxy

    saved = ctx.job["data"].get("research_steps", {}).get(key)
    if saved:
        return saved
    ctx.check_control()
    attempt = ctx.job["data"].get("attempt", 0)
    request_id = hashlib.sha256(f"{ctx.id}:{key}:{attempt}".encode()).hexdigest()
    import httpx

    receipts = list(dict.fromkeys(ctx.job["data"].get("research_request_ids", []) + [request_id]))
    db.update(ctx.id, data={"research_request_ids": receipts})

    try:
        value = await proxy(
            "POST",
            "/research/" + operation,
            {
                **body,
                "request_id": request_id,
                "config_version": ctx.job["data"]["input"]["research_config_version"],
            },
        )
    except httpx.HTTPError:
        raise HTTPException(503, "采集服务暂不可用，请明确重试") from None
    current = ctx.job["data"].get("research_steps", {})
    if operation != "extract" or value.get("results"):
        current[key] = value
        db.update(ctx.id, data={"research_steps": current})
        try:
            await proxy("DELETE", "/research/requests/" + request_id)
        except (HTTPException, httpx.HTTPError):
            db.update(ctx.id, data={"warning": "资料已保存，搜索服务临时副本尚待清理"})
    return value


async def collect_network(ctx, payload, result):
    facets = ("著作 核心观点", "访谈 问答", "表达 风格", "批评 争议", "决策 经历", "思想 时间线")
    urls = []
    failures = []
    for index, facet in enumerate(facets):
        ctx.progress("采集人物公开资料", completed=index, total=6)
        try:
            found = await research_step(
                ctx,
                f"search:{index}",
                "search",
                {"query": payload["person_snapshot"]["title"] + " " + facet, "max_results": 5},
            )
            for item in found.get("results", []):
                if item["url"] not in urls:
                    urls.append(item["url"])
        except HTTPException:
            failures.append({"stage": f"search:{index}", "error": "搜索失败，请明确重试"})
    urls = urls[:20]
    sources = []
    for index, url in enumerate(urls):
        try:
            found = await research_step(ctx, f"extract:{index}", "extract", {"urls": [url]})
            pages = found.get("results", [])
            if not pages or not pages[0].get("raw_content", "").strip():
                failures.append({"url": url, "error": "正文不可用"})
                continue
            text = pages[0]["raw_content"]
            if len(text) > 100000:
                failures.append({"url": url, "error": "正文超过单页 100000 字符限制，未截断或纳入"})
                continue
            fingerprint = hashlib.sha256((url + "\n" + text).encode()).hexdigest()
            source = next(
                (s for s in db.list("source") if s["data"].get("research_fingerprint") == fingerprint), None
            )
            if not source:
                from .main import import_content

                source = import_content(text.encode(), "公开网页.md", url, "", "copy")["source"]
                source = db.update(
                    source["id"],
                    data={
                        "source_type": "web_research",
                        "url": url,
                        "collected_at": now(),
                        "research_fingerprint": fingerprint,
                        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                    },
                )
            sources.append(source["id"])
            current = ctx.job["data"]
            bindings = current.get("research_bindings", {})
            if source["id"] not in bindings:
                bindings[source["id"]] = {
                    "source_version": source["version"],
                    "chapter_versions": {c["id"]: c["version"] for c in chapters_for(source["id"])},
                }
            db.update(
                ctx.id,
                data={
                    "resolved_source_ids": sorted(
                        set(current.get("resolved_source_ids", [])) | {source["id"]}
                    ),
                    "research_bindings": bindings,
                },
            )
        except HTTPException:
            failures.append({"url": url, "error": "提取失败，请明确重试"})
    db.update(result["id"], data={"research_sources": sources, "research_failures": failures})
    if failures and not ctx.job["data"].get("accept_partial_research"):
        raise StepFailure("联网采集部分失败，成功资料已保存；可明确重试，或在思想结果中选择基于已有材料继续")
    return sources


async def run(ctx, job):
    payload = job["data"]["input"]
    from .distillation.registry import get_method

    if payload["method_snapshot"] != get_method("nuwa").manifest():
        raise StepFailure("女娲方法版本已改变，请使用原版本恢复或重新创建任务")
    result = once(
        ctx.id,
        "thought-result",
        "distillation",
        payload["person_snapshot"]["title"] + " · 女娲思想蒸馏",
        {
            "distillation_type": "thought",
            "method_id": "nuwa",
            "method_snapshot": payload["method_snapshot"],
            "job_id": ctx.id,
            "person_id": payload["person_id"],
            "source_ids": payload["source_ids"],
            "source_versions": payload["source_versions"],
            "chapter_ids": payload["chapter_ids"],
            "chapter_versions": payload["chapter_versions"],
            "allow_network": payload["allow_network"],
            "card_ids": [],
            "card_versions": {},
            "extensions": {},
            "prompt": payload["prompt"],
        },
        status="running",
        parent_id=payload["person_id"],
    )
    source_versions = dict(payload["source_versions"])
    chapter_versions = dict(payload["chapter_versions"])
    ids = list(payload["source_ids"])
    chapter_ids = list(payload["chapter_ids"])
    if payload["allow_network"]:
        for sid in await collect_network(ctx, payload, result):
            require(sid, "source", usable=True)
            if sid not in ids:
                ids.append(sid)
            binding = ctx.job["data"]["research_bindings"][sid]
            source_versions.setdefault(sid, binding["source_version"])
            for cid, version in binding["chapter_versions"].items():
                if cid not in chapter_ids:
                    chapter_ids.append(cid)
                    chapter_versions[cid] = version
    chapter_map = {}
    for cid in chapter_ids:
        chapter = db.revision(cid, chapter_versions[cid])
        if not chapter or not db.get(cid):
            raise StepFailure("思想资料版本已不可用")
        chapter["_source_version"] = source_versions[chapter["data"]["source_id"]]
        chapter_map[cid] = chapter
    total = sum(len(c["data"].get("text", "")) for c in chapter_map.values())
    from .jobs import settings

    if not total or total > int(settings().get("max_distill_characters", 500000)):
        raise StepFailure("可用资料为空或超过本次字符限制，请缩小范围后新建任务")
    db.update(
        result["id"],
        data={
            "source_ids": ids,
            "source_versions": source_versions,
            "chapter_ids": chapter_ids,
            "chapter_versions": chapter_versions,
        },
    )
    observations = []
    for cid, chapter in chapter_map.items():
        for index, (_, _, text) in enumerate(chunks(chapter["data"].get("text", ""))):
            ctx.progress("材料整理与来源核对")
            value = await ctx.generate(
                UNTRUSTED
                + "\n提取人物的思想观察，按 writings/conversations/expression/external_views/decisions/timeline 分类。必须提供输入章节中的逐字引用，不将他人评价当成本人观点。",
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "person": payload["person_snapshot"]["title"],
                                "focus": payload["prompt"],
                                "chapter_id": cid,
                                "text": text,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
                schema=OBSERVATIONS,
                purpose="thought_distill",
                step_key=f"nuwa:materials:{cid}:{index}",
            )
            for observation in value["observations"]:
                refs = checked_references(observation.get("references", []), chapter_map)
                if refs:
                    observations.append({**observation, "references": refs})
    if not observations:
        raise StepFailure("材料中未提取到有真实引用支持的思想观察")
    reports = []
    for dimension in DIMENSIONS:
        relevant = [o for o in observations if o["dimension"] == dimension]
        if not relevant:
            reports.append({"dimension": dimension, "content": "资料不足，未作外部推断"})
            continue
        for index, group in enumerate(batches(relevant)):
            ctx.progress("六维分析 · " + dimension)
            report = await ctx.generate(
                UNTRUSTED
                + "\n整理该维度的人物思想、证据与矛盾。保留 chapter_id 和逐字引用。缺少材料的方面写明未知，不添加常识中的人物观点。",
                messages=[{"role": "user", "content": json.dumps(group, ensure_ascii=False)}],
                purpose="thought_distill",
                step_key=f"nuwa:dimension:{dimension}:{index}",
            )
            if len(report) > 12000:
                raise StepFailure("单维度报告过长，请缩小资料范围；不会静默截断")
            reports.append({"dimension": dimension, "content": report})
    encoded = json.dumps(reports, ensure_ascii=False)
    if len(encoded) > 60000:
        raise StepFailure("思想报告超过单次整合范围，请减少资料或缩小聚焦问题；不会静默截断")
    ctx.progress("候选认知规则提炼")
    candidate = await ctx.generate(
        UNTRUSTED
        + "\n依据女娲提炼认知规则：心智模型、决策启发式、价值观、分析步骤、表达、反模式、矛盾和局限。提供触发条件、执行行为、失效边界、归因及原文引用。没有依据的维度留空，不为凑数量补造。第三方评价不能冒充本人思想。",
        messages=[{"role": "user", "content": encoded}],
        schema=RULES,
        purpose="thought_distill",
        step_key="nuwa:candidates",
    )
    rules = []
    for index, rule in enumerate(candidate["rules"]):
        refs = checked_references(rule.get("references", []), chapter_map)
        rules.append(
            {
                **rule,
                "id": f"rule-{index + 1}",
                "references": refs,
                "structural_valid": bool(refs),
                "review_status": "pending_review"
                if refs and rule.get("attribution") not in {"inference", "third_party"}
                else "candidate",
            }
        )
    ctx.progress("三重验证、反例与矛盾检查")
    audit = await ctx.generate(
        UNTRUSTED
        + "\n独立审查规则与证据。逐项验证跨场景复现、迁移生成力和人物辨识度；识别第三方观点、反例、矛盾和不足。模型评价不等于人工审核。",
        messages=[{"role": "user", "content": json.dumps(rules, ensure_ascii=False)}],
        schema=ASSESS,
        purpose="thought_distill",
        step_key="nuwa:audit",
    )
    assessments = {a["rule_id"]: a for a in audit["assessments"]}
    for rule in rules:
        assessment = assessments.get(rule["id"], {})
        rule["model_assessment"] = assessment
        if not assessment.get("supported") or (
            rule["category"] == "mental_models"
            and not all(assessment.get(k) for k in ("cross_context", "generative", "distinctive"))
        ):
            rule["review_status"] = "candidate"
    ctx.progress("保存独立思想画像")
    profile = once(
        ctx.id,
        "cognitive-profile",
        "cognitive_profile",
        payload["person_snapshot"]["title"] + " · 思想画像",
        {
            "person_id": payload["person_id"],
            "distillation_id": result["id"],
            "source_ids": ids,
            "source_versions": source_versions,
            "chapter_versions": chapter_versions,
            "rules": rules,
            "missing_dimensions": candidate["missing_dimensions"],
            "origin": "nuwa",
            "method_version": payload["method_snapshot"]["version"],
            "identity_notice": "基于资料提炼的 AI 思想模拟，非本人、非官方授权代表",
        },
        status="draft",
        parent_id=payload["person_id"],
    )
    ctx.progress("独立问题集测试")
    tests = await ctx.generate(
        UNTRUSTED
        + "\n测试以下四类问题并记录回答、通过情况与原因：已知观点的证据一致性；矛盾语境的保留；资料未覆盖的新问题的诚实边界；要求伪造人物原话时的拒绝。只评估给定规则，禁止把模型自评称作客观保真度。",
        messages=[
            {
                "role": "user",
                "content": json.dumps(
                    {"rules": rules, "person": payload["person_snapshot"]["title"]}, ensure_ascii=False
                ),
            }
        ],
        schema=TESTS,
        purpose="thought_distill",
        step_key="nuwa:tests",
    )
    db.update(
        result["id"],
        status="completed",
        data={
            "cognitive_profile_id": profile["id"],
            "overview": payload["person_snapshot"]["title"] + "的独立思想蒸馏结果；需逐项人工审核后启用。",
            "extensions": {"reports": reports, "assessments": audit["assessments"], "tests": tests["tests"]},
            "calls": step_digest(ctx),
            "completed_at": now(),
        },
    )
    return {"distillation_id": result["id"], "cognitive_profile_id": profile["id"], "requires_review": True}
