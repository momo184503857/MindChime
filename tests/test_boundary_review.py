"""Independent regressions for knowledge scope, task identity and deletion boundaries."""

import asyncio
import json

import httpx
import pytest
import respx
from mindchime import domain, jobs, main
from mindchime.db import db
from mindchime.jobs import Ctx, StepFailure, enqueue
from mindchime.worker import Worker


@pytest.fixture(autouse=True)
def isolated_boundary_database(tmp_path, monkeypatch):
    db.reset(tmp_path / "boundary.sqlite3")
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.delenv("MINDCHIME_EMBEDDED_WORKER", raising=False)


def knowledge_fixture():
    text = "允许阅读的开头。绝不应再检索的秘密证据段。允许阅读的结尾。"
    secret = "绝不应再检索的秘密证据段。"
    source = db.create("source", "资料", {"format": "txt"})
    chapter = db.create(
        "chapter",
        "章节",
        {
            "source_id": source["id"],
            "text": text,
            "selected": True,
            "locator": {"type": "paragraph", "index": 1},
        },
        parent_id=source["id"],
    )
    ref = domain.reference(chapter, source, text.index(secret), text.index(secret) + len(secret))
    excluded = db.create(
        "card",
        "排除的卡",
        {
            "content": secret,
            "source_ids": [source["id"]],
            "chapter_ids": [chapter["id"]],
            "references": [ref],
        },
    )
    overlapping = db.create(
        "card",
        "引用重叠的另一张卡",
        {
            "content": secret,
            "source_ids": [source["id"]],
            "chapter_ids": [chapter["id"]],
            "references": [ref],
        },
    )
    agent = db.create(
        "agent",
        "范围助手",
        domain.agent_data(
            {
                "source_ids": [source["id"]],
                "chapter_ids": [chapter["id"]],
                "card_ids": [excluded["id"], overlapping["id"]],
                "excluded_card_ids": [excluded["id"]],
            }
        ),
    )
    return source, chapter, excluded, overlapping, agent, secret


async def test_excluded_card_removes_raw_evidence_and_overlapping_card():
    _, chapter, excluded, overlapping, agent, secret = knowledge_fixture()
    results, mode = await domain.retrieve(None, agent, "秘密证据", "scope")
    assert mode == "keyword"
    serialized = json.dumps(results, ensure_ascii=False)
    assert secret not in serialized
    assert all(not item["id"].startswith(f"card:{overlapping['id']}") for item in results)
    assert all(not item["id"].startswith(f"card:{excluded['id']}") for item in results)
    assert any("允许阅读" in item["text"] for item in results)
    for item in results:
        for ref in item["references"]:
            if ref["chapter_id"] == chapter["id"]:
                assert chapter["data"]["text"][ref["start"] : ref["end"]] == ref["quote"]


async def test_old_agent_reads_pinned_chapter_after_live_content_changes():
    _, chapter, _, _, agent, _ = knowledge_fixture()
    db.update(chapter["id"], data={"text": "NEW_VERSION_MUST_NOT_LEAK"})
    results, _ = await domain.retrieve(None, agent, "允许阅读", "old-version")
    assert "NEW_VERSION_MUST_NOT_LEAK" not in json.dumps(results)
    assert any("允许阅读" in item["text"] for item in results)


async def test_embedding_model_route_does_not_drift_mid_job():
    _, _, _, _, agent, _ = knowledge_fixture()
    settings = db.create("settings", "配置", {"purpose_profiles": {"embedding": "original-embedding"}})
    job = enqueue("chat", {"agent_ids": [agent["id"]], "text": "检索"}, "frozen-route")
    db.update(settings["id"], data={"purpose_profiles": {"embedding": "new-embedding"}})
    selected_profiles = []
    job_id = job["id"]

    class CaptureContext:
        id = job_id

        @property
        def job(self):
            return db.get(self.id, "job")

        async def pin_profile(self, profile_id):
            selected_profiles.append(profile_id)
            return 1

        async def embed(self, texts, *, step_key, profile_id=None):
            selected_profiles.append(profile_id)
            return [[1.0, 0.0] for _ in texts]

    await domain.retrieve(CaptureContext(), agent, "允许阅读", "route")
    assert selected_profiles and set(selected_profiles) == {"original-embedding"}


async def test_deleting_conversation_cleans_task_and_event_copies(monkeypatch):
    private_text = "PRIVATE_CONVERSATION_CONTENT_012345"
    conversation = db.create("conversation", "待删除会话", {"mode": "single", "agent_ids": []})
    message = domain.save_message(conversation["id"], "我", {"role": "user", "text": private_text})
    job = db.create(
        "job",
        "chat",
        {
            "kind": "chat",
            "input": {"conversation_id": conversation["id"], "text": private_text},
            "steps": {
                "answer": {
                    "request_id": "private-request",
                    "status": "completed",
                    "result": {"text": private_text},
                }
            },
        },
        status="completed",
    )
    jobs.emit_job(job)
    kept = db.create(
        "artifact", "独立保存的成果", {"content": "用户选择另存的笔记", "conversation_id": conversation["id"]}
    )
    cleaned = []

    async def purge(record):
        cleaned.append(record["id"])
        return True

    monkeypatch.setattr(main, "purge_ai_requests", purge)
    await main.delete_conversation(conversation["id"])
    assert db.get(message["id"]) is None and db.get(conversation["id"]) is None
    assert db.get(kept["id"]) is not None
    assert job["id"] in cleaned
    assert private_text not in json.dumps(db.list("job", include_deleted=True), ensure_ascii=False)
    assert private_text not in json.dumps(db.events(f"conversation:{conversation['id']}"), ensure_ascii=False)
    assert private_text not in json.dumps(db.events("jobs"), ensure_ascii=False)


async def test_late_provider_error_cannot_resurrect_cancelled_job(monkeypatch):
    job = enqueue("boundary_late_error", {}, "cancel-race")
    job = db.update(job["id"], status="running")

    async def handler(ctx, active):
        # Reproduce cancellation arriving after a provider response was read but before failure handling.
        db.update(active["id"], status="cancelled")
        raise StepFailure("Delayed upstream failure after explicit cancellation")

    monkeypatch.setitem(jobs.HANDLERS, "boundary_late_error", handler)
    await Worker().execute(job)
    assert db.get(job["id"])["status"] == "cancelled"


async def test_successful_steps_reused_and_profile_version_pinned():
    db.create("settings", "配置", {"default_profile_id": "profile-a"})
    job = enqueue("boundary", {}, "profile-version")
    job = db.update(job["id"], status="running")
    context = Ctx(job, asyncio.Event())
    submitted = []
    version = 1

    def accept(request):
        body = json.loads(request.content)
        submitted.append(body)
        return httpx.Response(202, json={"id": body["request_id"], "status": "queued"})

    def complete(request):
        return httpx.Response(
            200,
            json={
                "id": request.url.path.split("/")[-1],
                "status": "completed",
                "profile_version": 1,
                "result": {"text": "recorded successful result"},
                "usage": {},
            },
        )

    with respx.mock(assert_all_called=False) as upstream:
        upstream.get(jobs.AI_URL + "/ai/v1/profiles").mock(
            side_effect=lambda request: httpx.Response(200, json=[{"id": "profile-a", "version": version}])
        )
        upstream.post(jobs.AI_URL + "/ai/v1/requests").mock(side_effect=accept)
        upstream.get(url__regex=jobs.AI_URL + r"/ai/v1/requests/[^/]+$").mock(side_effect=complete)
        upstream.post(url__regex=jobs.AI_URL + r"/ai/v1/requests/[^/]+/ack$").respond(
            200, json={"status": "acknowledged"}
        )
        assert await context.generate("first", step_key="first") == "recorded successful result"
        version = 2
        assert await context.generate("first", step_key="first") == "recorded successful result"
        assert await context.generate("second", step_key="second") == "recorded successful result"
    assert len(submitted) == 2
    assert {item["profile_version"] for item in submitted} == {1}


async def test_embedding_retry_never_reuses_other_batch_vectors():
    candidates = [{"id": f"evidence-{i}", "text": str(i), "source_ids": []} for i in range(20)]

    class StepCacheContext:
        def __init__(self):
            self.cache = {}
            self.calls = 0

        async def pin_profile(self, profile_id):
            return 1

        async def embed(self, texts, *, step_key, profile_id=None):
            if step_key in self.cache:
                return self.cache[step_key]
            self.calls += 1
            if self.calls == 2:
                raise StepFailure("simulated provider failure in second batch")
            vectors = [[float(text), 1.0] for text in texts]
            self.cache[step_key] = vectors
            return vectors

    context = StepCacheContext()
    with pytest.raises(StepFailure):
        await domain.indexed_embeddings(context, candidates, "embedding", "retrieval:index")
    assert len(db.list("vector")) == 10
    result = await domain.indexed_embeddings(context, candidates, "embedding", "retrieval:index")
    assert [vector[0] for vector in result] == list(range(20))


async def test_event_cursors_remain_monotonic_after_private_cache_cleanup():
    conversation = db.create("conversation", "删除缓存", {"mode": "single", "agent_ids": []})
    domain.save_message(conversation["id"], "我", {"role": "user", "text": "待清除的私人文本"})
    last = db.emit("jobs", "job", {"progress": 1})
    await main.delete_conversation(conversation["id"])
    new = db.emit("jobs", "job", {"progress": 2})
    assert new["id"] > last["id"]
    assert new["id"] in [item["id"] for item in db.events("jobs", last["id"])]
