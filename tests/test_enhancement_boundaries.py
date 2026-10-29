"""Adversarial portable-asset and workflow-boundary tests. No live model calls."""

import copy
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mindchime.db import db
from mindchime.enhancements import router
from mindchime.extra import skills, transfer


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MINDCHIME_DATA_DIR", str(tmp_path / "data"))
    db.reset(tmp_path / "data" / "business.sqlite3")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client


def assets(name="A"):
    source = db.create("source", f"资料{name}", {"format": "txt"})
    chapter = db.create(
        "chapter",
        f"章节{name}",
        {
            "source_id": source["id"],
            "source_ids": [source["id"]],
            "text": f"FULL_PRIVATE_BOOK_{name}",
            "selected": True,
        },
        parent_id=source["id"],
    )
    card = db.create(
        "card",
        f"知识{name}",
        {
            "content": f"知识摘要{name}",
            "source_ids": [source["id"]],
            "chapter_ids": [chapter["id"]],
            "references": [
                {
                    "source_id": source["id"],
                    "source_version": 1,
                    "chapter_id": chapter["id"],
                    "chapter_version": 1,
                    "start": 0,
                    "end": 4,
                    "quote": "FULL",
                }
            ],
        },
    )
    return source, chapter, card


def read_manifest(package):
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        return json.loads(archive.read("manifest.json")), archive.namelist()


def build_package(records, revisions=None, originals=None, files=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": "mindchime",
                    "version": 1,
                    "records": records,
                    "revisions": revisions or [],
                    "originals": originals or [],
                },
                ensure_ascii=False,
            ),
        )
        for path, contents in (files or {}).items():
            archive.writestr(path, contents)
    return output.getvalue()


def restore_package(client, package):
    preview = client.post("/api/v1/imports/preview", files={"file": ("test.zip", package, "application/zip")})
    assert preview.status_code == 200, preview.text
    result = client.post(f"/api/v1/imports/{preview.json()['id']}/restore", json={"conflict": "copy"})
    assert result.status_code == 200, result.text
    return result.json(), preview.json()


def test_default_package_excludes_full_text_and_nested_credential_variants(client):
    source, chapter, card = assets()
    db.create(
        "skill",
        "带快照方法",
        {
            "card_ids": [card["id"]],
            "source_ids": [source["id"]],
            "chapter_snapshot": chapter,
            "apiKey": "PRIVATE_API_KEY",
            "nested": {"access_token": "PRIVATE_TOKEN"},
        },
    )
    response = client.get("/api/v1/export?kind=workspace&format=zip")
    manifest, names = read_manifest(response.content)
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "FULL_PRIVATE_BOOK" not in serialized
    assert "PRIVATE_API_KEY" not in serialized and "PRIVATE_TOKEN" not in serialized
    assert names == ["manifest.json"]
    assert "知识摘要" in serialized and '"quote": "FULL"' in serialized


def test_conversation_export_includes_older_agent_dependency_closure(client):
    first, _, first_card = assets("A")
    second, _, second_card = assets("B")
    agent = db.create(
        "agent",
        "变化的知识",
        {
            "source_ids": [first["id"]],
            "card_ids": [first_card["id"]],
            "card_versions": {first_card["id"]: 1},
            "model_profile_id": "old-local-model",
        },
    )
    conversation = db.create(
        "conversation",
        "保留旧知识",
        {
            "agent_ids": [agent["id"]],
            "agent_snapshots": {agent["id"]: {"version": 1, "title": agent["title"]}},
        },
    )
    db.update(
        agent["id"],
        data={
            "source_ids": [second["id"]],
            "card_ids": [second_card["id"]],
            "card_versions": {second_card["id"]: 1},
            "model_profile_id": "new-local-model",
        },
    )
    package = client.get(f"/api/v1/export?kind=conversation&id={conversation['id']}&format=zip").content
    manifest, _ = read_manifest(package)
    ids = {item["id"] for item in manifest["records"]}
    assert {first["id"], first_card["id"], second["id"], second_card["id"]}.issubset(ids)
    restored, _ = restore_package(client, package)
    mapping = restored["id_mapping"]
    old = db.revision(mapping[agent["id"]], 1)
    assert old["data"]["source_ids"] == [mapping[first["id"]]]
    assert old["data"]["card_versions"] == {mapping[first_card["id"]]: 1}
    assert old["data"].get("model_profile_id") is None
    copied_conversation = db.get(mapping[conversation["id"]])
    assert copied_conversation["data"]["agent_snapshots"][mapping[agent["id"]]]["version"] == 1
    copied_card = db.get(mapping[first_card["id"]])
    ref = copied_card["data"]["references"][0]
    assert ref["source_id"] == mapping[first["id"]]
    assert ref["chapter_version"] == 1 and ref["quote"] == "FULL"


def test_plain_content_equal_to_record_id_is_not_rewritten_or_exported_as_dependency(client):
    source, _, _ = assets()
    artifact = db.create("artifact", "ID也是普通文字", {"content": source["id"]})
    package = client.get(f"/api/v1/export?kind=artifact&id={artifact['id']}&format=zip").content
    manifest, _ = read_manifest(package)
    assert {record["id"] for record in manifest["records"]} == {artifact["id"]}
    restored, _ = restore_package(client, package)
    assert db.get(restored["id_mapping"][artifact["id"]])["data"]["content"] == source["id"]


def test_untrusted_original_path_cannot_read_arbitrary_backend_file(client, tmp_path):
    outside = tmp_path / "unrelated-secret.txt"
    outside.write_text("MUST_NOT_LEAVE_SERVER")
    source = db.create("source", "恶意路径元数据", {"format": "txt", "file_path": str(outside)})
    response = client.get(f"/api/v1/export?kind=source&id={source['id']}&format=zip&originals=true")
    assert response.status_code == 422
    assert "MUST_NOT_LEAVE_SERVER" not in response.text


def test_original_symlink_outside_managed_directory_is_rejected(client, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("SECRET")
    original_dir = tmp_path / "data" / "originals"
    original_dir.mkdir()
    link = original_dir / "link.txt"
    link.symlink_to(outside)
    source = db.create("source", "链接", {"file_path": str(link)})
    assert client.get(f"/api/v1/export?kind=source&id={source['id']}&originals=true").status_code == 422


def test_managed_original_can_roundtrip_without_trusting_manifest_paths(client, tmp_path):
    source, chapter, _ = assets()
    original_dir = tmp_path / "data" / "originals"
    original_dir.mkdir()
    original = original_dir / "owned.txt"
    original.write_text(chapter["data"]["text"])
    db.update(source["id"], data={"file_path": str(original)})
    package = client.get("/api/v1/export?kind=workspace&originals=true").content
    result, _ = restore_package(client, package)
    restored = db.get(result["id_mapping"][source["id"]])
    path = Path(restored["data"]["file_path"])
    assert path.parent == tmp_path / "data" / "transfers"
    assert path.read_text() == chapter["data"]["text"]
    assert restored["data"]["original_available"] is True


def test_missing_package_dependency_never_attaches_to_existing_local_private_card(client):
    source, _, card = assets()
    agent = db.create(
        "agent", "缺少依赖的导入Agent", {"source_ids": [source["id"]], "card_ids": [card["id"]]}
    )
    result, preview = restore_package(client, build_package([agent]))
    assert preview["missing"]
    restored = db.get(result["id_mapping"][agent["id"]])
    assert restored["status"] == "disabled"
    assert restored["data"]["card_ids"][0] != card["id"]
    assert db.get(restored["data"]["card_ids"][0]) is None


@pytest.mark.parametrize("mutation", ["revision_kind", "revision_version", "dependency_type"])
def test_malformed_historical_metadata_is_rejected_before_restore(client, mutation):
    source, _, _ = assets()
    revision = copy.deepcopy(source)
    records = [source]
    if mutation == "revision_kind":
        revision["kind"] = "agent"
    elif mutation == "revision_version":
        revision["version"] = 99
    else:
        records[0]["data"]["source_ids"] = {"some-local-source": True}
    response = client.post(
        "/api/v1/imports/preview", files={"file": ("bad.zip", build_package(records, [revision]))}
    )
    assert response.status_code == 422


def skill_run(client, steps=1):
    source, _, card = assets()
    response = client.post(
        "/api/v1/skills",
        json={
            "title": "方法",
            "data": {
                "card_ids": [card["id"]],
                "steps": [
                    {"title": f"步骤{i}", "instruction": "记录真实结果", "output": "结果"}
                    for i in range(steps)
                ],
            },
        },
    )
    assert response.status_code == 200, response.text
    skill = response.json()
    run = client.post(f"/api/v1/skills/{skill['id']}/runs", json={"inputs": {}}).json()
    return source, skill, run


def test_last_skill_step_replay_is_idempotent_and_changed_input_conflicts(client):
    _, _, run = skill_run(client)
    url = f"/api/v1/runs/{run['id']}/advance"
    payload = {"answer": "已经记录", "use_ai": False, "request_id": "same-step"}
    first = client.post(url, json=payload)
    assert first.status_code == 200 and first.json()["status"] == "completed"
    repeat = client.post(url, json=payload)
    assert repeat.status_code == 200 and len(repeat.json()["data"]["results"]) == 1
    changed = client.post(url, json={**payload, "answer": "不同结果"})
    assert changed.status_code == 409


async def test_ai_skill_handler_replay_after_commit_never_calls_model_again(client):
    _, _, run = skill_run(client)
    skills.commit_step(run, "已完成", "已有引导", "ai-step", use_ai=True)

    class NeverCall:
        async def generate(self, *args, **kwargs):
            raise AssertionError("Already committed AI step must not call the model")

    result = await skills.step(
        NeverCall(),
        {
            "data": {
                "input": {"run_id": run["id"], "step_index": 0, "request_id": "ai-step", "answer": "已完成"}
            }
        },
    )
    assert result["run_id"] == run["id"]


def test_disabled_source_cannot_be_hidden_by_omitting_skill_source_ids(client):
    source, _, card = assets()
    db.update(source["id"], status="disabled")
    response = client.post(
        "/api/v1/skills",
        json={
            "title": "不能使用",
            "data": {
                "card_ids": [card["id"]],
                "source_ids": [],
                "steps": [{"title": "一步", "instruction": "做", "output": "结果"}],
            },
        },
    )
    assert response.status_code == 409


def test_confirmed_graph_relation_can_be_disabled_without_reactivation(client):
    _, _, first = assets("A")
    _, _, second = assets("B")
    relation = client.post(
        "/api/v1/graph/relations",
        json={
            "data": {"from_id": first["id"], "to_id": second["id"], "type": "limit", "evidence": "前提不同"}
        },
    ).json()
    response = client.patch(f"/api/v1/graph/relations/{relation['id']}", json={"status": "disabled"})
    assert response.status_code == 200 and response.json()["status"] == "disabled"


def test_imported_disabled_skill_remains_unusable(client):
    _, skill, _ = skill_run(client)
    db.update(skill["id"], status="disabled", data={"disabled_reason": "用户停用"})
    package = client.get("/api/v1/export?kind=workspace").content
    result, _ = restore_package(client, package)
    copied_id = result["id_mapping"][skill["id"]]
    assert db.get(copied_id)["status"] == "disabled"
    assert client.post(f"/api/v1/skills/{copied_id}/runs", json={"inputs": {}}).status_code == 409


def test_simultaneous_restore_claims_preview_once(client, monkeypatch):
    assets()
    package = client.get("/api/v1/export?kind=workspace").content
    preview = client.post("/api/v1/imports/preview", files={"file": ("one.zip", package)}).json()
    expected_count = sum(preview["counts"].values())
    before_count = len(db.list())
    barrier = Barrier(2)
    original_read = transfer.read_package

    def synchronized_read(contents):
        result = original_read(contents)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(transfer, "read_package", synchronized_read)
    url = f"/api/v1/imports/{preview['id']}/restore"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, url, json={"conflict": "copy"}) for _ in range(2)]
        responses = [future.result(timeout=10) for future in futures]
    assert any(response.status_code == 200 for response in responses)
    assert all(response.status_code in {200, 409} for response in responses)
    assert len(db.list()) == before_count + expected_count


def test_successful_restore_rejects_changed_conflict_policy(client):
    source, _, _ = assets()
    package = build_package([source])
    _, preview = restore_package(client, package)
    response = client.post(f"/api/v1/imports/{preview['id']}/restore", json={"conflict": "skip"})
    assert response.status_code == 409


def test_skill_ai_duplicate_submission_reuses_job_and_blocks_input_edit(client, monkeypatch):
    _, _, run = skill_run(client)

    async def preflight(purpose, profile_id=None):
        return "test-only-model"

    monkeypatch.setattr(skills, "preflight", preflight)
    payload = {"answer": "记录了结果", "use_ai": True, "request_id": "same-ai-job"}
    first = client.post(f"/api/v1/runs/{run['id']}/advance", json=payload)
    second = client.post(f"/api/v1/runs/{run['id']}/advance", json=payload)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(db.list("job")) == 1
    changed = client.patch(f"/api/v1/runs/{run['id']}", json={"data": {"inputs": {"goal": "偷偷替换"}}})
    assert changed.status_code == 409


def test_skill_rejects_malformed_id_and_disabled_assistant(client, monkeypatch):
    _, _, run = skill_run(client)
    malformed = client.post(f"/api/v1/runs/{run['id']}/advance", json={"answer": "结果", "request_id": {}})
    assert malformed.status_code == 422
    agent = db.create("agent", "停用助手", {}, status="disabled")
    db.update(run["id"], data={"agent_id": agent["id"]})
    disabled = client.post(
        f"/api/v1/runs/{run['id']}/advance",
        json={"answer": "结果", "use_ai": True, "request_id": "disabled-agent"},
    )
    assert disabled.status_code == 409
