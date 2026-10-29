import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from mindchime import domain, jobs, main
from mindchime.db import db
from mindchime.jobs import Ctx, JobControl, enqueue, partial_json_text
from mindchime.worker import Worker


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    db.reset(tmp_path / "core.sqlite3")
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.delenv("MINDCHIME_EMBEDDED_WORKER", raising=False)
    return tmp_path


@pytest.fixture
def client(isolated):
    with TestClient(main.app) as client:
        yield client


def source_fixture(client, name="资料A", text="第一章 小步验证\n先用小实验收集证据，结果应能改变下一步。"):
    result = client.post("/api/v1/sources/paste", json={"title": name, "text": text})
    assert result.status_code == 200, result.text
    return result.json()


def agent_fixture(client, source, name="验证助手"):
    response = client.post("/api/v1/agents", json={"title": name, "data": {"source_ids": [source["source"]["id"]], "purpose": "验证条件"}})
    assert response.status_code == 200, response.text
    return response.json()


def test_import_duplicates_versions_and_real_offsets(client):
    imported = source_fixture(client)
    sid = imported["source"]["id"]
    cid = imported["chapters"][0]["id"]
    chapter = imported["chapters"][0]
    same = client.post("/api/v1/sources/paste", json={"title": "资料A", "text": chapter["data"]["text"]})
    assert same.status_code == 409
    changed = client.patch(f"/api/v1/chapters/{cid}", json={"data": {"text": "用户修正后的新内容"}})
    assert changed.status_code == 200
    evidence = client.get("/api/v1/evidence", params={"source_id": sid, "chapter_id": cid, "chapter_version": chapter["version"], "start": 0, "end": 7}).json()
    assert evidence["quote"] == chapter["data"]["text"][:7]
    assert client.get("/api/v1/evidence", params={"source_id": sid, "chapter_id": cid, "chapter_version": 1, "start": 0, "end": 99999}).status_code == 400


def test_agent_and_conversation_pin_versions(client):
    imported = source_fixture(client)
    agent = agent_fixture(client, imported)
    conversation = client.post("/api/v1/conversations", json={"title": "旧会话", "data": {"mode": "single", "agent_ids": [agent["id"]]}}).json()
    old_chapters = copy.deepcopy(agent["data"]["chapter_versions"])
    cid = imported["chapters"][0]["id"]
    client.patch(f"/api/v1/chapters/{cid}", json={"data": {"text": "新版本章节"}})
    updated = client.patch(f"/api/v1/agents/{agent['id']}", json={"title": "新名称", "data": {"style": "简洁"}}).json()
    assert updated["data"]["chapter_versions"] == old_chapters
    historical = domain.agent_in_conversation(conversation, agent["id"])
    assert historical["title"] == "验证助手"
    assert historical["version"] == agent["version"]
    response = client.post(f"/api/v1/conversations/{conversation['id']}/switch-version", json={"agent_id": agent["id"], "version": updated["version"]})
    assert response.status_code == 200
    assert any(m["data"]["role"] == "system" for m in domain.conversation_messages(conversation["id"]))


def test_new_agent_can_explicitly_select_old_source_version(client):
    imported = source_fixture(client)
    source, chapter = imported["source"], imported["chapters"][0]
    client.patch(f"/api/v1/chapters/{chapter['id']}", json={"data": {"text": "NEW_SOURCE_TEXT"}})
    response = client.post("/api/v1/agents", json={"title": "旧版本助手", "data": {
        "source_ids": [source["id"]], "source_versions": {source["id"]: source["version"]}}})
    assert response.status_code == 200, response.text
    agent = response.json()
    assert agent["data"]["chapter_versions"][chapter["id"]] == chapter["version"]
    preview = client.get(f"/api/v1/sources/{source['id']}?version={source['version']}").json()
    assert preview["chapters"][0]["data"]["text"] == chapter["data"]["text"]
    assert domain.knowledge_summary(agent)["updates_available"]
    bad = client.post("/api/v1/agents", json={"title": "无效版本", "data": {"source_ids": [source["id"]], "source_versions": {source["id"]: 999999}}})
    assert bad.status_code == 400


def test_draft_requires_explicit_trial(client):
    imported = source_fixture(client)
    agent = agent_fixture(client, imported)
    db.update(agent["id"], status="draft")
    payload = {"title": "试聊", "data": {"mode": "single", "agent_ids": [agent["id"]]}}
    assert client.post("/api/v1/conversations", json=payload).status_code == 400
    payload["data"]["trial"] = True
    assert client.post("/api/v1/conversations", json=payload).status_code == 200


def test_mixed_card_source_deletion_and_other_source_survives(client):
    first = source_fixture(client)
    second = source_fixture(client, "资料B", "第一章 边界\n先明确不能接受的代价。")
    a, b = first["source"]["id"], second["source"]["id"]
    card = db.create("card", "两者结合", {"content": "混合结论", "source_ids": [a, b], "references": []})
    skill = db.create("skill", "检验步骤", {"source_ids": [a, b], "card_ids": [card["id"]]})
    memory = db.create("memory", "资料观点", {"content": "据A所得", "source_ids": [a]}, status="candidate")
    response = client.delete(f"/api/v1/sources/{a}?mode=derived&history=redact")
    assert response.status_code == 200, response.text
    assert db.get(card["id"]) is None
    assert not db.revisions(card["id"])
    assert db.get(b, "source") is not None
    assert db.get(skill["id"])["status"] == "disabled"
    assert db.get(memory["id"])["status"] == "disabled"
    assert not db.revisions(first["chapters"][0]["id"])
    assert not Path(first["source"]["data"]["file_path"]).exists()


def test_only_original_delete_retains_cards_not_raw_revision(client):
    imported = source_fixture(client)
    sid = imported["source"]["id"]
    card = db.create("card", "小步", {"content": "可追溯提炼", "source_ids": [sid], "references": []})
    response = client.delete(f"/api/v1/sources/{sid}?mode=file")
    assert response.status_code == 200
    assert db.get(card["id"])
    cid = imported["chapters"][0]["id"]
    assert all("text" not in revision["data"] for revision in db.revisions(cid))


def test_merge_split_preserve_old_evidence(client):
    imported = source_fixture(client, text="第一章 方法\n先验证。\n第二章 边界\n再检查代价。")
    original = imported["chapters"]
    result = client.post("/api/v1/chapters/merge", json={"ids": [x["id"] for x in original]}).json()
    assert "先验证" in result["data"]["text"] and "再检查" in result["data"]["text"]
    split = client.post(f"/api/v1/chapters/{result['id']}/split", json={"offset": 8})
    assert split.status_code == 200
    assert "".join(x["data"]["text"] for x in split.json()) == result["data"]["text"]
    assert db.revision(original[0]["id"], 1)["data"]["text"] == original[0]["data"]["text"]


def test_idempotency_and_one_active_conversation_job(isolated):
    first = enqueue("chat", {"conversation_id": "c", "text": "x"}, "request-a")
    assert enqueue("chat", {"conversation_id": "c", "text": "x"}, "request-a")["id"] == first["id"]
    with pytest.raises(ValueError, match="不同内容"):
        enqueue("chat", {"conversation_id": "c", "text": "y"}, "request-a")
    with pytest.raises(ValueError, match="未结束任务"):
        enqueue("chat", {"conversation_id": "c", "text": "x"}, "request-b")


def test_no_model_is_not_false_queued_success(client):
    imported = source_fixture(client)
    response = client.post(f"/api/v1/sources/{imported['source']['id']}/distill", json={"request_id": "no-model"})
    assert response.status_code == 409
    assert not db.list("job")


def test_main_mounts_all_enhancements_under_versioned_api(client):
    for path in ("artifacts", "skills", "runs", "memories", "graph"):
        response = client.get("/api/v1/"+path)
        assert response.status_code == 200, (path, response.text)
    assert client.get("/artifacts").status_code == 404


@pytest.mark.parametrize("status", ["disabled", "failed", "cleaning", "deleting"])
def test_unusable_source_cannot_keep_agent_available(client, status):
    imported = source_fixture(client)
    agent = agent_fixture(client, imported)
    db.update(imported["source"]["id"], status=status)
    assert domain.knowledge_summary(agent)["available"] is False
    with pytest.raises(ValueError):
        domain.validate_sources([imported["source"]["id"]])


@pytest.mark.asyncio
async def test_ctx_cached_result_profile_lock_and_ack(isolated):
    db.create("settings", "settings", {"default_profile_id": "p1"})
    job = enqueue("test", {}, "test-ctx")
    db.update(job["id"], status="running")
    with respx.mock(assert_all_called=False) as mock:
        mock.get(jobs.AI_URL+"/ai/v1/profiles").mock(return_value=httpx.Response(200, json=[{"id": "p1", "version": 3}]))
        submitted = mock.post(jobs.AI_URL+"/ai/v1/requests").mock(return_value=httpx.Response(200, json={"id": "request-1", "status": "queued"}))
        mock.get(jobs.AI_URL+"/ai/v1/requests/request-1").mock(return_value=httpx.Response(200, json={"id": "request-1", "status": "completed", "result": {"text": "真实服务返回格式样例"}, "profile_version": 3}))
        ack = mock.post(jobs.AI_URL+"/ai/v1/requests/request-1/ack").mock(return_value=httpx.Response(200, json={"ok": True}))
        ctx = Ctx(job)
        first = await ctx.generate("question", step_key="one")
        second = await ctx.generate("question", step_key="one")
        assert first == second
        assert submitted.call_count == 1 and ack.call_count == 1
        assert json.loads(submitted.calls.last.request.content)["profile_version"] == 3
        assert db.get(job["id"])["data"]["steps"]["one"]["status"] == "completed"


@pytest.mark.asyncio
async def test_pause_stops_after_completed_step_and_resume_has_no_duplicates(isolated):
    job = enqueue("two_steps", {})
    recorded = []
    async def handler(ctx, job):
        if not ctx.job["data"].get("first_done"):
            recorded.append(1)
            ctx.progress("first", first_done=True)
            db.update(job["id"], status="pause_requested")
        ctx.check_control()
        recorded.append(2)
        return {"done": True}
    jobs.register_handler("two_steps", handler)
    worker = Worker()
    await worker.execute(db.claim_job())
    assert db.get(job["id"])["status"] == "paused"
    assert recorded == [1]
    db.update(job["id"], status="queued")
    await worker.execute(db.claim_job())
    assert recorded == [1, 2]
    assert db.get(job["id"])["status"] == "completed"


def test_stream_json_never_displays_control_fields():
    assert partial_json_text('{"text":"你好\\n这是正文", "citation_ids":[') == "你好\n这是正文"
    assert partial_json_text('{"text":"你\\u597') == "你"
    assert partial_json_text('{"citation_ids":[') == ""


@pytest.mark.asyncio
async def test_retry_recovers_completed_ai_request_without_new_provider_call(isolated):
    db.create("settings", "settings", {"default_profile_id": "p1"})
    job = enqueue("test", {}, "recover-completed")
    db.update(job["id"], status="running", data={"attempt": 1, "profile_snapshots": {"p1": 3},
        "steps": {"summary": {"status": "failed", "request_id": "existing-completed", "attempt": 0, "profile_id": "p1", "error": ""}}})
    with respx.mock(assert_all_called=False) as mock:
        submitted = mock.post(jobs.AI_URL+"/ai/v1/requests").mock(return_value=httpx.Response(500))
        recovered = mock.get(jobs.AI_URL+"/ai/v1/requests/existing-completed").mock(return_value=httpx.Response(200, json={"id": "existing-completed", "status": "completed", "result": {"text": "原调用已经完成的总结"}, "profile_version": 3}))
        ack = mock.post(jobs.AI_URL+"/ai/v1/requests/existing-completed/ack").mock(return_value=httpx.Response(200, json={"ok": True}))
        text = await Ctx(db.get(job["id"])).generate("summary", step_key="summary")
        assert text == "原调用已经完成的总结"
        assert submitted.call_count == 0 and recovered.call_count == 1 and ack.call_count == 1


def test_progress_events_do_not_copy_private_step_payloads(isolated):
    job = enqueue("test", {"text": "PRIVATE_INPUT"})
    job = db.update(job["id"], data={"steps": {"a": {"result": {"vectors": [[1]*2000], "text": "PRIVATE_OUTPUT"}}}, "stage": "处理中"})
    jobs.emit_job(job)
    event = db.events("jobs")[-1]
    serialized = json.dumps(event, ensure_ascii=False)
    assert "PRIVATE_INPUT" not in serialized and "PRIVATE_OUTPUT" not in serialized
    assert len(serialized) < 1000


def test_card_references_require_real_matching_source_ranges(client):
    imported = source_fixture(client)
    source, chapter = imported["source"], imported["chapters"][0]
    ref = {"source_id": source["id"], "source_version": source["version"], "chapter_id": chapter["id"], "chapter_version": chapter["version"], "start": 0, "end": 3, "quote": "伪造原文"}
    payload = {"title": "手工卡", "data": {"content": "个人归纳", "source_ids": [source["id"]], "references": [ref]}}
    assert client.post("/api/v1/cards", json=payload).status_code == 400
    ref["quote"] = chapter["data"]["text"][:3]
    response = client.post("/api/v1/cards", json=payload)
    assert response.status_code == 200
    card = response.json()
    ref["end"] = 99999
    assert client.patch(f"/api/v1/cards/{card['id']}", json={"data": {"references": [ref]}}).status_code == 400


def test_demo_real_chapters_and_deduplicated_references(client):
    sources = client.post("/api/v1/demo/load").json()["sources"]
    for source in sources:
        chapters = client.get(f"/api/v1/sources/{source['id']}").json()["chapters"]
        selected = [c for c in chapters if c["data"]["selected"]]
        assert len(selected) == 2
        assert all(c["title"].startswith(("第一章", "第二章")) for c in selected)
    ref = {"source_id": "s", "chapter_id": "c", "chapter_version": 1, "start": 1, "end": 3, "quote": "内容"}
    assert domain.dedupe_references([ref, dict(ref)]) == [ref]


@pytest.mark.asyncio
async def test_bound_retrieval_cannot_read_unselected_source(client):
    first = source_fixture(client)
    second = source_fixture(client, "私有B", "绝密答案在第二本书")
    agent = agent_fixture(client, first)
    job = enqueue("test", {})
    evidence, mode = await domain.retrieve(Ctx(job), agent, "绝密答案", "retrieve")
    assert mode == "keyword"
    assert all(second["source"]["id"] not in item.get("source_ids", []) for item in evidence)
    assert all("绝密答案" not in item["text"] for item in evidence)


@pytest.mark.asyncio
async def test_multi_agent_partial_retry_preserves_successful_drafts(client):
    imported = source_fixture(client)
    job = enqueue('agent_generate', {'source_ids': [imported['source']['id']], 'count': 3}, 'partial-agent-test')
    class FakeContext:
        def __init__(self):
            self.calls = []
            self.fail = True
        def check_control(self): pass
        def progress(self, *args, **kwargs): pass
        async def generate(self, prompt, **kwargs):
            key = kwargs['step_key']; self.calls.append(key)
            if self.fail and key == 'drafts:1': raise RuntimeError('temporary failure')
            return {'agents': [{'name': '草稿'+key, 'perspective': key, 'description': '不同分析角度'}]}
    ctx = FakeContext()
    partial = await domain.generate_agents(ctx, job)
    assert partial['partial'] and len(partial['agents']) == 2
    ids = {a['id'] for a in partial['agents']}
    ctx.fail = False; ctx.calls.clear()
    finished = await domain.generate_agents(ctx, job)
    assert not finished['partial'] and len(finished['agents']) == 3
    assert ctx.calls == ['drafts:1']
    assert ids.issubset({a['id'] for a in finished['agents']})


def test_single_card_deletion_disables_dependants(client):
    source=source_fixture(client)
    card=db.create('card','方法',{'source_ids':[source['source']['id']],'content':'观察'})
    skill=db.create('skill','实践',{'card_ids':[card['id']]})
    relation=db.create('relation','关系',{'from_id':card['id'],'to_id':'other'})
    assert client.delete('/api/v1/cards/'+card['id']).status_code==200
    assert db.get(skill['id'])['status']=='disabled'
    assert db.get(relation['id'])['status']=='disabled'


def test_old_evidence_and_file_keep_original_version(client):
    source=source_fixture(client); sid=source['source']['id']; chapter=source['chapters'][0]; version=source['source']['version']
    old=source['source']['data']['file_path']
    changed=client.post('/api/v1/sources/paste',json={'title':'新版名称','text':'另一版正文','duplicate_action':'version','source_id':sid})
    assert changed.status_code==200
    assert client.get(f'/api/v1/sources/{sid}/file',params={'version':version}).content==Path(old).read_bytes()
    evidence=client.get('/api/v1/evidence',params={'source_id':sid,'source_version':version,'chapter_id':chapter['id'],'chapter_version':chapter['version'],'start':0,'end':3}).json()
    assert evidence['source']['title']=='资料A'
    assert client.get(f'/api/v1/sources/{sid}/file?version=99999').status_code==404


@pytest.mark.asyncio
async def test_dynamic_api_defaults_match_confirmed_plan(client,monkeypatch):
    source=source_fixture(client); a=agent_fixture(client,source); b=agent_fixture(client,source,'另一个视角')
    conv=client.post('/api/v1/conversations',json={'title':'动态','data':{'mode':'group','agent_ids':[a['id'],b['id']]}}).json()
    async def ready(*args,**kwargs):return 'configured'
    monkeypatch.setattr(main,'verify_conversation_models',ready)
    result=client.post(f"/api/v1/conversations/{conv['id']}/discussions",json={'topic':'如何确定行动的边界','mode':'dynamic','summary':False}).json()
    assert result['data']['input']['max_speeches']==9
    assert result['data']['input']['max_minutes']==20


@pytest.mark.asyncio
async def test_semantic_recall_includes_cards_outside_keyword_top_48(client):
    source=source_fixture(client)
    target=db.create('card','目标',{'source_ids':[source['source']['id']],'content':'独特的目标方法 TARGET'})
    cards=[target]+[db.create('card',f'其他卡{i}',{'source_ids':[source['source']['id']],'content':f'一般内容{i}'}) for i in range(60)]
    agent=db.create('agent','全部知识',domain.agent_data({'source_ids':[source['source']['id']],'card_ids':[c['id'] for c in cards[::-1]]}))
    class FakeContext:
        job={'data':{'model_routes':{'purpose_profiles':{'embedding':'semantic'}}}}
        async def pin_profile(self,*args):return 1
        async def embed(self,texts,**kwargs):return [[1.,0.] if 'TARGET' in t or t=='unrelated-question' else [0.,1.] for t in texts]
    selected,mode=await domain.retrieve(FakeContext(),agent,'unrelated-question','recall')
    assert mode=='hybrid' and target['id'] in selected[0]['id']
