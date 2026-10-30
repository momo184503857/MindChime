import io
import json
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mindchime.db import db
from mindchime.enhancements import router


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MINDCHIME_DATA_DIR", str(tmp_path))
    db.reset(tmp_path / "business.sqlite3")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client


def assets():
    source = db.create("source", "资料 A", {"format": "txt", "file_path": "/private/never/export.txt"})
    chapter = db.create("chapter", "章节", {"source_id": source["id"], "text": "完整原书私有正文", "locator": {"type": "paragraph", "index": 1}}, parent_id=source["id"])
    card = db.create("card", "小步行动", {"content": "先做一次小尝试", "source_ids": [source["id"]],
        "chapter_ids": [chapter["id"]], "references": [{"source_id": source["id"], "chapter_id": chapter["id"], "chapter_version": 1, "start": 0, "end": 2, "quote": "完整"}]})
    agent = db.create("agent", "实验助手", {"source_ids": [source["id"]], "card_ids": [card["id"]], "model_profile_id": "secret-profile"})
    return source, chapter, card, agent


def test_export_is_portable_without_raw_book_or_credentials(client):
    source, chapter, card, agent = assets()
    db.create("settings", "settings", {"api_key": "MUST_NOT_EXPORT"})
    result = client.get("/api/v1/export", params={"kind": "agent", "id": agent["id"], "format": "zip"})
    assert result.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        manifest_text = archive.read("manifest.json").decode()
        manifest = json.loads(manifest_text)
    assert "完整原书私有正文" not in manifest_text
    assert "MUST_NOT_EXPORT" not in manifest_text
    assert "/private/" not in manifest_text
    assert card["id"] in {r["id"] for r in manifest["records"]}
    assert manifest["missing_originals"] == [source["id"]]


def test_restore_copy_remaps_all_dependencies_and_retains_versions(client):
    source, chapter, card, agent = assets()
    db.update(card["id"], data={"content": "用户修正后的方法"})
    package = client.get("/api/v1/export?kind=workspace&format=zip")
    preview = client.post("/api/v1/imports/preview", files={"file": ("assets.zip", package.content, "application/zip")})
    assert preview.status_code == 200
    assert len(preview.json()["conflicts"]) == 4
    result = client.post(f"/api/v1/imports/{preview.json()['id']}/restore", json={"conflict": "copy"})
    assert result.status_code == 200, result.text
    mapping = result.json()["id_mapping"]
    new_card = db.get(mapping[card["id"]])
    assert new_card["version"] == 2
    assert new_card["data"]["source_ids"] == [mapping[source["id"]]]
    assert db.revision(new_card["id"], 1)["data"]["content"] == "先做一次小尝试"
    assert db.get(mapping[chapter["id"]])["data"]["text"] == ""
    assert client.post(f"/api/v1/imports/{preview.json()['id']}/restore", json={"conflict": "copy"}).json() == result.json()


def test_package_path_traversal_rejected(client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": "mindchime", "version": 1, "records": []}))
        archive.writestr("../escape", "bad")
    result = client.post("/api/v1/imports/preview", files={"file": ("bad.zip", buffer.getvalue())})
    assert result.status_code == 422


def test_skill_runs_freeze_steps_and_disabled_skill_cannot_advance(client):
    source, chapter, card, agent = assets()
    skill = client.post("/api/v1/skills", json={"title": "小步实践", "data": {
        "card_ids": [card["id"]], "source_ids": [source["id"]],
        "steps": [{"title": "选一个动作", "instruction": "写下可逆的小动作", "output": "一个动作"}]}}).json()
    run = client.post(f"/api/v1/skills/{skill['id']}/runs", json={"inputs": {"goal": "试读"}}).json()
    db.update(skill["id"], data={"steps": [{"title": "已修改", "instruction": "新步骤", "output": "新产物"}]})
    assert db.get(run["id"])["data"]["skill_snapshot"]["data"]["steps"][0]["title"] == "选一个动作"
    db.update(skill["id"], status="disabled")
    result = client.post(f"/api/v1/runs/{run['id']}/advance", json={"answer": "读一页", "use_ai": False})
    assert result.status_code == 409
    assert db.get(run["id"])["data"]["step_index"] == 0


def test_memory_requires_activation_and_deleted_dependencies_block_it(client):
    source, _, _, agent = assets()
    memory = db.create("memory", "偏好", {"content": "喜欢分步骤", "agent_id": agent["id"], "source_ids": []}, status="candidate")
    assert client.patch(f"/api/v1/memories/{memory['id']}", json={"status": "active"}).json()["data"]["confirmed"] is True
    db.update(memory["id"], data={"source_ids": [source["id"]]}, status="disabled")
    db.delete(source["id"])
    assert client.patch(f"/api/v1/memories/{memory['id']}", json={"status": "active"}).status_code == 404


def test_graph_preserves_disabled_metadata_when_card_deleted(client):
    source, _, card, _ = assets()
    second = db.create("card", "边界", {"source_ids": [source["id"]], "content": "检查代价"})
    relation = client.post("/api/v1/graph/relations", json={"data": {"from_id": card["id"], "to_id": second["id"],
        "type": "limit", "evidence": "行动应受代价限制"}}).json()
    db.purge(card["id"])
    db.update(relation["id"], status="disabled")
    result = client.get("/api/v1/graph").json()
    node = next(n for n in result["nodes"] if n["id"] == card["id"])
    assert node["status"] == "disabled"
    assert node["data"].get("content") is None
    assert result["edges"][0]["status"] == "disabled"


def test_revisions_and_optimistic_conflict(client):
    source, _, _, _ = assets()
    updated = db.update(source["id"], title="修改名称", expected_version=1)
    with pytest.raises(ValueError):
        db.update(source["id"], title="过期编辑", expected_version=1)
    assert db.revision(source["id"], 1)["title"] == "资料 A"
    assert db.get(source["id"])["title"] == updated["title"]


def test_markdown_exports_preserve_usable_assets(client):
    source, chapter, card, agent = assets()
    db.update(source['id'], data={'chapter_ids':[chapter['id']], 'distillation':{'overview':'完整总览'},'coverage':{'failures':['未处理范围']}})
    db.update(chapter['id'],data={'latest_summary':'章节提炼结果'})
    db.update(agent['id'],data={'framework':'先检验再判断','boundaries':'不保证结果'})
    text=client.get('/api/v1/export',params={'kind':'source','id':source['id'],'format':'markdown'}).text
    assert all(term in text for term in ['完整总览','未处理范围','章节提炼结果','小步行动'])
    text=client.get('/api/v1/export',params={'kind':'agent','id':agent['id'],'format':'markdown'}).text
    assert all(term in text for term in ['先检验再判断','不保证结果','先做一次小尝试'])
    assert '/private/' not in text and 'secret-profile' not in text
    conv=db.create('conversation','讨论',{})
    db.create('message','成员',{'text':'尚未完成的内容','speaker_name':'旧名称'},parent_id=conv['id'],status='incomplete')
    db.create('artifact','结束总结',{'content':'真实分歧','conversation_id':conv['id']})
    text=client.get('/api/v1/export',params={'kind':'conversation','id':conv['id'],'format':'markdown'}).text
    assert all(term in text for term in ['尚未完成的内容','旧名称','incomplete','真实分歧'])


def test_practice_is_independent_of_agent_changes_and_deletion(client):
    source, _, card, agent = assets()
    skill=client.post('/api/v1/skills',json={'title':'方法','data':{'card_ids':[card['id']],'steps':[{'title':'观察','instruction':'写观察','output':'记录'}]}}).json()
    run=client.post(f"/api/v1/skills/{skill['id']}/runs",json={}).json()
    db.update(agent['id'],data={'framework':'新思考框架'})
    db.delete(agent['id'])
    assert 'agent_snapshot' not in run['data']
    assert 'agent_id' not in run['data']
    advanced=client.post(f"/api/v1/runs/{run['id']}/advance",json={'answer':'已记录','use_ai':False})
    assert advanced.status_code==200
    assert advanced.json()['status']=='completed'
