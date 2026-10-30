import json
import time

import pytest
from fastapi.testclient import TestClient
from mindchime import auth, main
from mindchime.access import identity
from mindchime.db import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    db.reset(tmp_path / "business.sqlite3")
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.delenv("MINDCHIME_EMBEDDED_WORKER", raising=False)
    with TestClient(main.app) as client:
        yield client


def login(client, name):
    accounts = json.loads((db.path.parent / "local-accounts.json").read_text())
    response = client.post("/api/v1/auth/login", json=next(a for a in accounts if a["username"] == name))
    assert response.status_code == 200, response.text
    return response.json()


def source(client):
    return client.post(
        "/api/v1/sources/paste",
        json={
            "title": "公开测试资料",
            "text": "第一章 方法\n先写下问题，再记录观察。",
            "duplicate_action": "copy",
        },
    ).json()


def test_auth_roles_cookie_expiry_and_idempotent_seed(client):
    assert client.get("/api/v1/sources").status_code == 401
    assert (
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    )
    user = login(client, "user")
    assert user["role"] == "user"
    assert client.get("/api/v1/sources", headers={"Origin": "http://127.0.0.1:9999"}).status_code == 403
    assert client.get("/api/v1/auth/me").json()["username"] == "user"
    assert client.get("/api/v1/profiles").status_code == 403
    assert client.post("/api/v1/persons", json={"title": "人物"}).status_code == 403
    assert client.patch("/api/v1/settings", json={}).status_code == 403
    assert (
        client.post("/api/v1/conversations", json={"data": {"model_profile_id": "fake"}}).status_code == 403
    )
    assert (
        client.post("/api/v1/artifacts", json={}, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    before = (db.path.parent / "local-accounts.json").read_text()
    auth.initialize()
    assert before == (db.path.parent / "local-accounts.json").read_text()
    with auth.connection() as conn:
        conn.execute("UPDATE local_sessions SET expires_at=?", (time.time() - 1,))
    assert client.get("/api/v1/auth/me").status_code == 401
    login(client, "admin")
    assert client.get("/api/v1/profiles").status_code != 403
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/sources").status_code == 401


def test_publication_is_explicit_and_draft_does_not_leak(client):
    login(client, "admin")
    item = source(client)
    sid = item["source"]["id"]
    private = client.post(
        "/api/v1/artifacts", json={"title": "管理员私人", "data": {"content": "私人文字"}}
    ).json()
    login(client, "user")
    assert client.get("/api/v1/sources").json() == []
    assert client.get("/api/v1/sources/" + sid).status_code == 404
    assert client.get("/api/v1/artifacts/" + private["id"]).status_code == 404
    assert client.get("/api/v1/search?q=私人").json() == []
    login(client, "admin")
    assert client.post("/api/v1/publications/" + sid).status_code == 200
    client.patch("/api/v1/sources/" + sid, json={"title": "不能泄露的草稿"})
    login(client, "user")
    assert client.get("/api/v1/sources").json()[0]["title"] == "公开测试资料"
    assert client.get("/api/v1/search?q=不能泄露").json() == []
    assert client.get("/api/v1/sources/" + sid + "?version=999").status_code == 404
    assert client.get("/api/v1/export?kind=workspace").status_code == 403
    assert client.get("/api/v1/export?kind=source&id=" + sid).status_code == 403
    own = client.post("/api/v1/artifacts", json={"title": "用户成果", "data": {"content": "我的记录"}}).json()
    login(client, "admin")
    assert client.get("/api/v1/artifacts/" + own["id"]).status_code == 404
    assert client.delete("/api/v1/publications/" + sid).status_code == 200
    login(client, "user")
    assert client.get("/api/v1/sources").json() == []


def test_skill_binding_rejected_and_ownership(client):
    login(client, "admin")
    item = source(client)
    sid = item["source"]["id"]
    card = client.post(
        "/api/v1/cards",
        json={
            "title": "方法卡",
            "data": {"type": "method", "content": "先写问题", "source_ids": [sid], "references": []},
        },
    ).json()
    data = {
        "card_ids": [card["id"]],
        "steps": [{"title": "记录", "instruction": "记录结果", "output": "笔记"}],
    }
    assert (
        client.post(
            "/api/v1/skills", json={"title": "无人物实践", "data": {**data, "agent_id": "fake"}}
        ).status_code
        == 422
    )
    skill = client.post("/api/v1/skills", json={"title": "无人物实践", "data": data}).json()
    assert (
        client.post("/api/v1/skills/" + skill["id"] + "/runs", json={"agent_id": "fake"}).status_code == 422
    )
    run = client.post("/api/v1/skills/" + skill["id"] + "/runs", json={"inputs": {}}).json()
    assert "agent_id" not in run["data"]
    login(client, "user")
    assert client.get("/api/v1/runs/" + run["id"]).status_code == 404
    assert (
        client.post("/api/v1/runs/" + run["id"] + "/advance", json={"answer": "覆盖他人"}).status_code == 404
    )


def test_thought_default_off_and_invalid_references_cannot_be_reviewed(client):
    login(client, "admin")
    person = client.post("/api/v1/persons", json={"title": "原创人物"}).json()
    response = client.post(
        "/api/v1/distillations", json={"distillation_type": "thought", "person_id": person["id"]}
    )
    assert response.status_code == 422
    profile = db.create(
        "cognitive_profile",
        "无依据画像",
        {
            "person_id": person["id"],
            "source_ids": [],
            "rules": [
                {"id": "r1", "review_status": "candidate", "references": [], "structural_valid": False}
            ],
        },
        status="draft",
    )
    response = client.patch(
        "/api/v1/cognitive-profiles/" + profile["id"],
        json={"rules": [{"id": "r1", "review_status": "verified"}]},
    )
    assert response.status_code == 422
    methods = client.get("/api/v1/distillation-methods").json()["methods"]
    assert len([m for m in methods if m["distillation_type"] == "knowledge"]) == 6
    assert [m["id"] for m in methods if m["distillation_type"] == "thought"] == ["nuwa"]


@pytest.mark.asyncio
async def test_nuwa_independent_profile_review_thought_chat_and_published_history(client, monkeypatch):
    from mindchime import domain, thought
    from mindchime.jobs import Ctx, enqueue

    login(client, "admin")
    imported = source(client)
    sid = imported["source"]["id"]
    chapter = imported["chapters"][0]
    person = client.post("/api/v1/persons", json={"title": "原创思考者"}).json()

    async def preflight(*args, **kwargs):
        return "test-model"

    async def proxy(method, path, body=None):
        if path == "/profiles":
            return [{"id": "test-model", "version": 1}]
        raise AssertionError("关闭联网时不允许搜索：" + path)

    monkeypatch.setattr(thought, "preflight", preflight)
    monkeypatch.setattr(main, "proxy", proxy)
    response = client.post(
        "/api/v1/distillations",
        json={"distillation_type": "thought", "person_id": person["id"], "source_ids": [sid]},
    )
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["data"]["input"]["allow_network"] is False
    quote = "先写下问题，再记录观察。"

    class Nuwa(Ctx):
        def __init__(self, job):
            super().__init__(job)
            self.calls = []

        async def generate(self, prompt, **kw):
            key = kw["step_key"]
            cached = self.job["data"].get("steps", {}).get(key)
            if cached:
                return cached["result"]["json"]
            self.calls.append(key)
            refs = [{"chapter_id": chapter["id"], "quote": quote}]
            if key.startswith("nuwa:materials:"):
                value = {"observations": [{"dimension": "writings", "content": quote, "references": refs}]}
            elif key.startswith("nuwa:dimension:"):
                return json.dumps({"content": quote, "references": refs}, ensure_ascii=False)
            elif key == "nuwa:candidates":
                value = {
                    "rules": [
                        {
                            "name": "观察再判断",
                            "category": "decision_heuristics",
                            "behavior": "先记录观察再决定下一步。",
                            "trigger": "需要判断下一步",
                            "limitations": "不适用于无法观察的情境",
                            "attribution": "paraphrase",
                            "references": refs,
                        }
                    ],
                    "missing_dimensions": ["访谈资料不足"],
                }
            elif key == "nuwa:audit":
                value = {
                    "assessments": [
                        {
                            "rule_id": "rule-1",
                            "supported": True,
                            "cross_context": False,
                            "generative": True,
                            "distinctive": True,
                            "reason": "原文支持此启发式",
                        }
                    ]
                }
            else:
                value = {
                    "tests": [
                        {
                            "question": "资料未涉及的问题？",
                            "answer": "无法确定",
                            "passed": True,
                            "reason": "保留诚实边界",
                        }
                    ]
                }
            steps = self.job["data"].get("steps", {})
            steps[key] = {"status": "completed", "result": {"json": value}}
            db.update(self.id, data={"steps": steps})
            return value

    output = await thought.run(Nuwa(job), job)
    profile = db.get(output["cognitive_profile_id"])
    result = db.get(output["distillation_id"])
    assert profile["status"] == "draft" and profile["data"]["rules"][0]["review_status"] == "pending_review"
    assert result["data"]["distillation_type"] == "thought"
    assert db.list("card") == []
    assert (
        client.post(
            "/api/v1/agents", json={"title": "尚未审核", "data": {"cognitive_profile_id": profile["id"]}}
        ).status_code
        == 409
    )
    response = client.patch(
        "/api/v1/cognitive-profiles/" + profile["id"],
        json={"rules": [{"id": "rule-1", "review_status": "verified"}], "status": "active"},
    )
    assert response.status_code == 200, response.text
    profile = response.json()
    for rid in (sid, person["id"], profile["id"]):
        response = client.post("/api/v1/publications/" + rid)
        assert response.status_code == 200, response.text
    agent = client.post(
        "/api/v1/agents",
        json={
            "title": "纯思想测试",
            "data": {
                "cognitive_profile_id": profile["id"],
                "cognitive_profile_version": profile["version"],
                "purpose": "思考",
            },
        },
    ).json()
    assert agent["data"]["agent_type"] == "thought"
    assert client.post("/api/v1/publications/" + agent["id"]).status_code == 200
    user = login(client, "user")
    conversation = client.post(
        "/api/v1/conversations",
        json={"title": "用户思考", "data": {"mode": "single", "agent_ids": [agent["id"]]}},
    ).json()
    assert "id" in conversation, conversation
    with identity(user):
        task = enqueue("chat", {"conversation_id": conversation["id"]})

        class Reply(Ctx):
            async def generate(self, prompt, **kw):
                inputs = json.loads(kw["messages"][0]["content"])
                assert inputs["cognitive_profile"]["rules"][0]["name"] == "观察再判断"
                return {
                    "text": "这是基于资料框架的模拟分析。先记录可观察的事实。",
                    "basis": "来源支持",
                    "citation_ids": [inputs["evidence"][0]["id"]],
                    "response_to": [],
                }

        message = await domain.reply(Reply(task), conversation, agent["id"], "如何判断下一步", "reply")
        assert message["owner_user_id"] == user["id"]
        assert message["data"]["references"][0]["quote"] == quote
    login(client, "admin")
    client.patch("/api/v1/agents/" + agent["id"], json={"title": "新发布名称"}).json()
    assert client.post("/api/v1/publications/" + agent["id"]).status_code == 200
    login(client, "user")
    with identity(user):
        assert domain.agent_in_conversation(conversation, agent["id"])["title"] == "纯思想测试"
    login(client, "admin")
    client.delete("/api/v1/publications/" + profile["id"])
    login(client, "user")
    assert client.get("/api/v1/agents").json() == []


@pytest.mark.asyncio
async def test_worker_uses_persisted_user_owner(client, monkeypatch):
    from mindchime.jobs import HANDLERS, enqueue
    from mindchime.worker import Worker

    user = login(client, "user")
    with identity(user):
        job = enqueue("owner-test", {})

    async def handler(ctx, job):
        return {"id": db.create("artifact", "任务产物", {"content": "仅用户可见"})["id"]}

    monkeypatch.setitem(HANDLERS, "owner-test", handler)
    await Worker().execute(job)
    result = db.get(job["id"])
    artifact = db.get(result["data"]["result"]["id"])
    assert artifact["owner_user_id"] == user["id"]
    login(client, "admin")
    assert client.get("/api/v1/artifacts/" + artifact["id"]).status_code == 404


def test_exact_card_revision_review_and_result_publication(client):
    login(client, "admin")
    imported = source(client)
    sid = imported["source"]["id"]
    chapter = imported["chapters"][0]
    from mindchime.domain import reference

    card = db.create(
        "card",
        "待核对方法",
        {
            "content": "先观察",
            "source_ids": [sid],
            "review_status": "pending",
            "references": [reference(chapter, imported["source"], 0, 5)],
        },
    )
    result = db.create(
        "distillation",
        "知识批次",
        {
            "source_ids": [sid],
            "source_id": sid,
            "source_version": 1,
            "card_ids": [card["id"]],
            "card_versions": {card["id"]: 1},
            "distillation_type": "knowledge",
        },
        status="completed",
        parent_id=sid,
    )
    assert client.post("/api/v1/publications/" + sid).status_code == 200
    assert client.post("/api/v1/reviews/" + card["id"], json={"version": 1}).status_code == 200
    assert client.post("/api/v1/publications/" + result["id"]).status_code == 200
    login(client, "user")
    cards = client.get("/api/v1/cards").json()
    assert cards[0]["version"] == 1 and cards[0]["data"]["review_status"] == "verified"
    login(client, "admin")
    client.delete("/api/v1/publications/" + sid)
    login(client, "user")
    assert client.get("/api/v1/cards").json() == []


def test_published_source_file_delete_cleans_cached_originals(client):
    login(client, "admin")
    imported = source(client)
    sid = imported["source"]["id"]
    assert client.post("/api/v1/publications/" + sid).status_code == 200
    assert client.delete("/api/v1/sources/" + sid + "?mode=file").status_code == 200
    login(client, "user")
    data = client.get("/api/v1/sources/" + sid).json()
    assert data["source"]["status"] == "file_deleted"
    assert all(not c["data"].get("text") for c in data["chapters"])
    chapter = imported["chapters"][0]
    result = client.get(
        "/api/v1/evidence",
        params={"source_id": sid, "chapter_id": chapter["id"], "chapter_version": 1, "start": 0, "end": 5},
    )
    assert result.json()["status"] == "missing"


def test_legacy_migration_keeps_versions_and_does_not_resume_tasks(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE records (id TEXT PRIMARY KEY,kind TEXT,title TEXT,status TEXT,version INTEGER,parent_id TEXT,data JSON,created_at TEXT,updated_at TEXT)"
        )
        for id, kind, data, status in [
            ("old-skill", "skill", {"agent_id": "old-agent", "steps": []}, "active"),
            (
                "old-run",
                "run",
                {
                    "agent_id": "old-agent",
                    "agent_snapshot": {"title": "旧人物"},
                    "results": [{"answer": "已完成步骤"}],
                },
                "active",
            ),
            ("old-job", "job", {"kind": "skill_step", "input": {"agent_id": "old-agent"}}, "queued"),
        ]:
            conn.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?)",
                (id, kind, id, status, 7, None, json.dumps(data), "2026-01-01", "2026-01-01"),
            )
    db.reset(path)
    auth.initialize()
    assert db.get("old-run")["version"] == 7
    assert db.get("old-run")["owner_user_id"] == "local-admin"
    assert db.get("old-run")["data"]["results"][0]["answer"] == "已完成步骤"
    assert "agent_id" not in db.get("old-skill")["data"]
    assert db.get("old-job")["status"] == "interrupted"
    assert db.get("old-job")["data"]["legacy_requires_restart"]
    before = (tmp_path / "local-accounts.json").read_text()
    auth.initialize()
    assert (tmp_path / "local-accounts.json").read_text() == before
    from mindchime.publications import all_publications

    assert all_publications() == []


def test_unrelated_publications_do_not_expand_target_dependency_graph(client, monkeypatch):
    from mindchime import publications

    login(client, "admin")
    imported = source(client)
    sid = imported["source"]["id"]
    assert client.post("/api/v1/publications/" + sid).status_code == 200
    person = client.post("/api/v1/persons", json={"title": "独立人物"}).json()
    assert client.post("/api/v1/publications/" + person["id"]).status_code == 200
    for i in range(8):
        agent = client.post(
            "/api/v1/agents",
            json={"title": f"无关知识助手{i}", "data": {"source_ids": [sid], "raw_source_ids": [sid]}},
        ).json()
        assert client.post("/api/v1/publications/" + agent["id"]).status_code == 200
    original = publications.visible_snapshot
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[0])
        assert len(calls) <= 10, "读取单个人物不应遍历无关智能体的依赖"
        return original(*args, **kwargs)

    monkeypatch.setattr(publications, "visible_snapshot", counted)
    assert counted(person["id"])["id"] == person["id"]
    assert calls == [person["id"]]


@pytest.mark.asyncio
async def test_job_event_stream_filters_owners_and_checks_topic_access(client, monkeypatch):
    from mindchime.jobs import emit_job, enqueue

    login(client, "admin")
    admin_job = enqueue("maintenance", {})
    user = login(client, "user")
    assert client.get("/api/v1/events", params={"topic": "job:" + admin_job["id"]}).status_code == 404
    with identity(user):
        user_job = enqueue("chat", {})
        emit_job(admin_job)
        emit_job(user_job)

        class Request:
            def __init__(self):
                self.state = type("State", (), {"actor": user})()
                self.cookies = {auth.COOKIE: "test-token"}
                self.headers = {}
                self.checks = 0

            async def is_disconnected(self):
                self.checks += 1
                return self.checks > 1

        monkeypatch.setattr(auth, "actor_for_token", lambda token: user)
        response = await main.events(Request())
        chunks = []
        async for piece in response.body_iterator:
            chunks.append(piece)
        content = "".join(chunks)
        assert user_job["id"] in content
        assert admin_job["id"] not in content
