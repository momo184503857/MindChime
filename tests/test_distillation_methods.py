import copy
import json
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient
from mindchime import domain, main
from mindchime.db import db
from mindchime.distillation import engine
from mindchime.distillation.registry import get_method, methods
from mindchime.distillation.store import activate, migrate_legacy, result_detail
from mindchime.jobs import Ctx, JobControl, enqueue


@pytest.fixture
def client(tmp_path, monkeypatch):
    db.reset(tmp_path / "test.sqlite3")
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.delenv("MINDCHIME_EMBEDDED_WORKER", raising=False)
    with TestClient(main.app) as value:
        yield value


def source(client):
    return client.post(
        "/api/v1/sources/paste",
        json={
            "title": "原创方法测试",
            "text": "第一章 尝试\n先进行小步实验，记录观察。\n第二章 边界\n只有代价可承受时才进行实验。",
        },
    ).json()


def job_for(imported, method="basic", request=None):
    return enqueue(
        "distill",
        {
            "source_id": imported["source"]["id"],
            "source_version": imported["source"]["version"],
            "chapter_ids": [c["id"] for c in imported["chapters"]],
            "chapter_versions": {c["id"]: c["version"] for c in imported["chapters"]},
            "method_id": method,
            "method_snapshot": get_method(method).manifest(),
            "prompt": "保留适用边界",
            "result_schema_version": 1,
        },
        request,
    )


class Model(Ctx):
    """Durable fake model boundary, with fail/cancel injection and contract-valid outputs."""

    def __init__(self, job):
        super().__init__(job)
        self.calls, self.fail, self.cancel, self.bad_quote, self.bad_test = [], None, None, False, False

    async def generate(self, prompt, **kw):
        key = kw["step_key"]
        cached = self.job["data"].get("steps", {}).get(key)
        if cached and cached["status"] == "completed":
            return copy.deepcopy(cached["result"]["json"])
        self.calls.append(key)
        if self.cancel and self.cancel in key:
            raise JobControl("paused")
        if self.fail and self.fail in key:
            raise RuntimeError("injected interruption")
        data = json.loads(kw["messages"][0]["content"])
        schema = kw["schema"]["properties"]
        if "cards" in schema:
            value = {
                "summary": "先试验，再核对代价。",
                "cards": [
                    {
                        "title": "方法 " + key.split(":")[-1],
                        "type": "method",
                        "content": "小步实验 " + key.split(":")[-1],
                        "attribution": "作者观点",
                        "applicability": "代价可承受",
                        "limitations": "不可忽略代价",
                        "references": [{"quote": "假造引文" if self.bad_quote else data["source_text"][:10]}],
                    }
                ],
                "warnings": [],
            }
        elif "overview" in schema:
            value = {
                "overview": "尝试应有边界。",
                "relationships": [{"from": "made-up", "to": "other", "type": "支持", "basis": "伪关系"}],
                "limitations": ["要评估代价"],
            }
        else:
            entries = [
                entry for item in data["inputs"] for entry in item.get("material", []) if "card_id" in entry
            ]
            if "repairs" in schema:
                value = {"repairs": [], "warnings": []}
            else:
                value = {
                    "sections": [
                        {
                            "title": key,
                            "content": "方法特色成果。",
                            "card_ids": [e["card_id"] for e in entries],
                        }
                    ],
                    "decisions": [
                        {"card_id": e["card_id"], "verdict": "supported", "reason": "原文支持"}
                        for e in entries
                    ],
                    "tests": [
                        {
                            "card_id": e["card_id"],
                            "question": "超出代价是否继续？",
                            "answer": "停止",
                            "passed": not self.bad_test,
                            "reason": "检查边界",
                        }
                        for e in entries
                    ],
                    "warnings": [],
                }
        from jsonschema import validate

        validate(value, kw["schema"])
        steps = self.job["data"].get("steps", {})
        steps[key] = {
            "status": "completed",
            "result": {"json": value},
            "usage": {"total_tokens": 1},
            "profile_id": "fixture",
            "profile_version": 1,
        }
        db.update(self.id, data={"steps": steps})
        return copy.deepcopy(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", [m.id for m in methods().values() if m.distillation_type == "knowledge"])
async def test_methods_produce_isolated_results_and_validated_relations(client, method):
    imported = source(client)
    job = job_for(imported, method)
    model = Model(job)
    value = await domain.distill(model, job)
    result = result_detail(value["distillation_id"])
    assert result["status"] == "completed"
    assert not db.get(imported["source"]["id"])["data"].get("active_distillation_id")
    assert result["data"]["integration"]["relationships"] == []
    assert result["data"]["quality"]["invalid_relations"] == 1
    assert all(c["data"]["references"] for c in result["cards"])
    assert {c["data"]["distillation_id"] for c in result["cards"]} == {result["id"]}
    for stage in get_method(method).stages:
        assert any(stage.id in call for call in model.calls), (method, stage.id)
    if method != "basic":
        assert result["data"]["extensions"]
    assert result["data"]["external_sources"]["status"] == "not_executed"


@pytest.mark.asyncio
async def test_partial_retry_reuses_successful_calls_and_stable_cards(client):
    imported = source(client)
    job = job_for(imported, "book-to-skill")
    model = Model(job)
    model.fail = ":patterns:"
    first = await engine.run(model, job)
    assert first["partial"]
    with pytest.raises(ValueError, match="完整"):
        activate(first["distillation_id"])
    ids = {c["id"] for c in result_detail(first["distillation_id"])["cards"]}
    model.fail = None
    model.calls.clear()
    second = await engine.run(model, job)
    assert not second["partial"]
    assert model.calls and not any(":frameworks" in c or ":prepare:" in c for c in model.calls)
    assert ids == {c["id"] for c in result_detail(second["distillation_id"])["cards"]}


@pytest.mark.asyncio
async def test_result_binding_switch_does_not_change_old_agents_or_conversations(client):
    imported = source(client)
    first_job, second_job = job_for(imported), job_for(imported, "bolan")
    first = (await engine.run(Model(first_job), first_job))["distillation_id"]
    second = (await engine.run(Model(second_job), second_job))["distillation_id"]
    sid = imported["source"]["id"]
    assert (
        client.post("/api/v1/agents", json={"title": "no-choice", "data": {"source_ids": [sid]}}).status_code
        == 400
    )
    activate(first)
    response = client.post("/api/v1/agents", json={"title": "固定结果", "data": {"source_ids": [sid]}})
    assert response.status_code == 200, response.text
    agent = response.json()
    conversation = client.post(
        "/api/v1/conversations",
        json={"title": "历史", "data": {"mode": "single", "agent_ids": [agent["id"]]}},
    ).json()
    activate(second)
    assert db.get(agent["id"]) == agent
    assert domain.agent_in_conversation(conversation, agent["id"]) == agent
    new = domain.agent_data({"source_ids": [sid]})
    assert new["distillation_ids"][sid] == second
    assert set(new["card_ids"]).isdisjoint(agent["data"]["card_ids"])
    wrong = result_detail(first)["cards"][0]["id"]
    with pytest.raises(ValueError, match="不属于"):
        domain.agent_data({"source_ids": [sid], "distillation_ids": {sid: second}, "card_ids": [wrong]})
    raw = domain.agent_data({"source_ids": [sid], "raw_source_ids": [sid]})
    assert not raw["card_ids"] and raw["chapter_ids"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["quote", "pressure"])
async def test_unverified_capabilities_cannot_be_used(client, failure):
    imported = source(client)
    job = job_for(imported, "cangjie")
    model = Model(job)
    model.bad_quote = failure == "quote"
    model.bad_test = failure == "pressure"
    rid = (await engine.run(model, job))["distillation_id"]
    result = result_detail(rid)
    assert all(c["status"] == "disabled" for c in result["cards"])
    card = result["cards"][0]
    with pytest.raises(ValueError, match="不可绑定"):
        domain.agent_data(
            {
                "source_ids": [imported["source"]["id"]],
                "distillation_ids": {imported["source"]["id"]: rid},
                "card_ids": [card["id"]],
            }
        )
    assert (
        client.post(
            "/api/v1/skills",
            json={
                "title": "不可使用",
                "data": {"card_ids": [card["id"]], "steps": [{"instruction": "执行"}]},
            },
        ).status_code
        == 409
    )


@pytest.mark.asyncio
async def test_cancel_preserves_partial_output_and_method_version_is_pinned(client):
    imported = source(client)
    job = job_for(imported, "bolan")
    model = Model(job)
    model.cancel = ":thinking:"
    with pytest.raises(JobControl):
        await engine.run(model, job)
    assert result_detail(engine.result_id(job["id"]))["status"] == "incomplete"
    model.cancel = None
    model.calls.clear()
    assert not (await engine.run(model, job))["partial"]
    assert not any(":argument" in call for call in model.calls)
    changed = copy.deepcopy(job)
    changed["data"]["input"]["method_snapshot"]["version"] = "unavailable"
    with pytest.raises(Exception, match="方法版本"):
        await engine.run(model, changed)


@pytest.mark.asyncio
async def test_export_restore_remaps_result_bindings_and_delete_purges_results(client):
    imported = source(client)
    job = job_for(imported, "book-to-skill")
    rid = (await engine.run(Model(job), job))["distillation_id"]
    activate(rid)
    agent = db.create("agent", "使用结果", domain.agent_data({"source_ids": [imported["source"]["id"]]}))
    package = client.get("/api/v1/export", params={"kind": "agent", "id": agent["id"], "format": "zip"})
    assert package.status_code == 200
    preview = client.post(
        "/api/v1/imports/preview", files={"file": ("assets.zip", package.content, "application/zip")}
    )
    assert preview.status_code == 200, preview.text
    restored = client.post("/api/v1/imports/" + preview.json()["id"] + "/restore", json={"conflict": "copy"})
    assert restored.status_code == 200, restored.text
    new_agent = next(a for a in db.list("agent") if a["id"] != agent["id"])
    sid = new_agent["data"]["source_ids"][0]
    new_result = new_agent["data"]["distillation_ids"][sid]
    assert sid != imported["source"]["id"] and new_result != rid
    assert db.get(new_result)["data"]["source_id"] == sid
    text = client.get("/api/v1/export", params={"kind": "distillation", "id": rid, "format": "markdown"}).text
    assert "方法特色成果" in text and "保留适用边界" in text
    deleted = client.delete("/api/v1/sources/" + imported["source"]["id"] + "?mode=derived")
    assert deleted.status_code == 200, deleted.text
    assert not db.get(rid) and not db.revisions(rid)
    assert db.get(new_result)


def test_api_catalog_validation_and_legacy_backfill(client, monkeypatch):
    catalog = client.get("/api/v1/distillation-methods").json()
    assert catalog["default_method_id"] == "cangjie" and len(catalog["methods"]) == 7
    imported = source(client)
    sid = imported["source"]["id"]
    assert (
        client.post(f"/api/v1/sources/{sid}/distill", json={"method_id": "external-code"}).status_code == 400
    )
    assert (
        client.post(f"/api/v1/sources/{sid}/distill", json={"prompt": "a", "focus": "b"}).status_code == 400
    )
    job = enqueue(
        "distill", {"source_id": sid, "source_version": 1, "chapter_ids": [], "chapter_versions": {}}
    )
    db.update(
        job["id"],
        status="completed",
        data={"result": {"integration": {"overview": "旧总览"}, "coverage": {"completed": []}}},
    )
    db.update(sid, data={"latest_distill_job_id": job["id"]})
    migrate_legacy()
    migrate_legacy()
    assert len(db.list("distillation")) == 1
    assert db.get(sid)["data"]["active_distillation_id"] == engine.result_id(job["id"])


def test_chunking_covers_every_character_with_overlap():
    text = "每段都有不同位置\n" * 6000
    parts = list(engine.chunks(text))
    assert parts[0][0] == 0 and parts[-1][1] == len(text)
    assert all(a[1] >= b[0] for a, b in pairwise(parts))
    assert all(text[a:b] == piece for a, b, piece in parts)


@pytest.mark.asyncio
async def test_failed_extraction_blocks_dependent_reports_then_retry_covers_all_chapters(client):
    imported = source(client)
    job = job_for(imported, "book-reader")
    model = Model(job)
    second_id = imported["chapters"][1]["id"]
    model.fail = second_id
    first = await engine.run(model, job)
    assert first["partial"]
    assert not any(":critical:" in key or ":application:" in key for key in model.calls)
    first_cards = {c["id"] for c in result_detail(first["distillation_id"])["cards"]}
    model.fail = None
    model.calls.clear()
    second = await engine.run(model, job)
    result = result_detail(second["distillation_id"])
    assert not second["partial"]
    assert set(result["data"]["coverage"]["completed"]) == {c["id"] for c in imported["chapters"]}
    assert first_cards <= {c["id"] for c in result["cards"]}
    assert any(ref["chapter_id"] == second_id for c in result["cards"] for ref in c["data"]["references"])
    assert not any(imported["chapters"][0]["id"] in key for key in model.calls)
    assert any(":critical:" in key for key in model.calls)


@pytest.mark.asyncio
async def test_result_cannot_expand_chapter_range_and_changed_source_cannot_activate(client):
    imported = source(client)
    job = job_for(imported)
    payload = copy.deepcopy(job["data"]["input"])
    payload["chapter_ids"] = payload["chapter_ids"][:1]
    job = db.update(job["id"], data={"input": payload})
    rid = (await engine.run(Model(job), job))["distillation_id"]
    sid = imported["source"]["id"]
    with pytest.raises(ValueError, match="处理范围"):
        domain.agent_data(
            {
                "source_ids": [sid],
                "distillation_ids": {sid: rid},
                "chapter_ids": [imported["chapters"][1]["id"]],
            }
        )
    db.update(job["id"], status="completed")
    activate(rid)
    changed = client.patch(
        "/api/v1/chapters/" + imported["chapters"][0]["id"],
        json={"data": {"text": "新原文，旧结果不能成为当前。"}},
    )
    assert changed.status_code == 200, changed.text
    assert db.get(sid)["data"].get("active_distillation_id") is None
    with pytest.raises(ValueError, match="原文已变化"):
        activate(rid)
    # Historical selection remains pinned, independently of current source edits.
    old = domain.agent_data({"source_ids": [sid], "distillation_ids": {sid: rid}})
    assert old["chapter_versions"][imported["chapters"][0]["id"]] == imported["chapters"][0]["version"]


@pytest.mark.asyncio
async def test_submission_pins_model_and_method_snapshot_and_legacy_focus(client, monkeypatch):
    imported = source(client)

    async def ready(*args, **kwargs):
        return "fixture-profile"

    async def profiles(*args, **kwargs):
        return [{"id": "fixture-profile", "version": 7}]

    monkeypatch.setattr(main, "ensure_model", ready)
    monkeypatch.setattr(main, "proxy", profiles)
    path = "/api/v1/sources/" + imported["source"]["id"] + "/distill"
    first = client.post(path, json={"focus": "旧客户端提示词", "request_id": "same-request"})
    assert first.status_code == 200, first.text
    job = first.json()
    assert job["data"]["input"]["method_id"] == "basic"
    assert job["data"]["input"]["prompt"] == "旧客户端提示词"
    assert job["data"]["profile_snapshots"] == {"fixture-profile": 7}
    assert (
        client.post(path, json={"focus": "旧客户端提示词", "request_id": "same-request"}).json()["id"]
        == job["id"]
    )
    assert client.post(path, json={"prompt": "不同提示词", "request_id": "same-request"}).status_code == 400
    await engine.run(Model(job), job)  # Serialized snapshot compares identically after persistence.


def test_schema_error_diagnostic_reports_missing_keys_without_echoing_values():
    from ai_service.adapters import ProviderError
    from ai_service.app import decode_structured

    schema = {
        "type": "object",
        "required": ["cards", "summary"],
        "properties": {"cards": {"type": "array"}, "summary": {"type": "string"}},
    }
    with pytest.raises(ProviderError) as error:
        decode_structured('{"private":"do-not-echo-this"}', schema)
    assert "cards" in str(error.value) and "summary" in str(error.value)
    assert "do-not-echo-this" not in str(error.value)


@pytest.mark.asyncio
async def test_feature_sections_cannot_reintroduce_rejected_or_unselected_cards(client):
    from mindchime.distillation.store import usable_sections

    imported = source(client)
    job = job_for(imported)
    rid = (await engine.run(Model(job), job))["distillation_id"]
    cards = result_detail(rid)["cards"]
    allowed, denied = cards[0]["id"], cards[-1]["id"]
    if denied == allowed:
        denied = db.create("card", "拒绝能力", {"source_ids": [imported["source"]["id"]]}, status="disabled")[
            "id"
        ]
    db.update(denied, status="disabled")
    result = db.update(
        rid,
        data={
            "extensions": [
                {
                    "report": {
                        "sections": [
                            {"title": "允许", "content": "合法知识", "card_ids": [allowed]},
                            {"title": "候选", "content": "禁止生成的候选内容", "card_ids": [denied]},
                            {"title": "混合", "content": "混入候选", "card_ids": [allowed, denied]},
                            {"title": "无锚点", "content": "无依据的特色文字", "card_ids": []},
                        ]
                    }
                }
            ]
        },
    )
    assert [s["title"] for s in usable_sections(result, [allowed, denied])] == ["允许"]


def test_result_relationships_are_dependencies_and_remap_without_rewriting_notes():
    from mindchime.extra.transfer import dependency_ids, remap

    data = {
        "integration": {
            "relationships": [{"from": "card-a", "to": "card-b", "type": "支持", "basis": "源文依据"}]
        },
        "notes": {"from": "card-a", "to": "card-b"},
    }
    assert dependency_ids(data) == {"card-a", "card-b"}
    mapped = remap(data, {"card-a": "new-a", "card-b": "new-b"})
    assert mapped["integration"]["relationships"][0]["from"] == "new-a"
    assert mapped["integration"]["relationships"][0]["to"] == "new-b"
    assert mapped["notes"] == data["notes"]
