"""All HTTP model responses in this file are explicit test doubles, never application fixtures."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from ai_service.app import create_app
from ai_service.store import Store

TOKEN = "test-service-token"
SECRET = "test-private-credential"


def profile_body(**overrides):
    return {
        "id": "test-model",
        "name": "测试模型",
        "protocol": "openai_chat",
        "base_url": "https://provider.test/v1",
        "model": "test-model-v1",
        "api_key": SECRET,
        "capabilities": {
            "stream": False,
            "vision": False,
            "json": True,
            "embedding": False,
            "context_tokens": 8192,
        },
        **overrides,
    }


def completion(text="测试结果", **overrides):
    return {
        "model": "test-model-v1",
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        **overrides,
    }


@asynccontextmanager
async def running(tmp_path, handler=None, *, seed=False, token=TOKEN):
    if handler is None:
        handler = lambda request: httpx.Response(200, json=completion())
    app = create_app(tmp_path, service_token=token, transport=httpx.MockTransport(handler), seed=seed)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://local.test",
            headers={"X-Service-Token": TOKEN},
        ) as client,
    ):
        yield client, app


async def add_profile(client, **overrides):
    response = await client.post("/ai/v1/profiles", json=profile_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


async def submit(client, request_id="request-1", **overrides):
    response = await client.post(
        "/ai/v1/requests",
        json={
            "request_id": request_id,
            "operation": "generate",
            "profile_id": "test-model",
            "prompt": "测试用资料",
            **overrides,
        },
    )
    return response


async def finished(client, request_id="request-1"):
    for _ in range(500):
        response = await client.get(f"/ai/v1/requests/{request_id}")
        assert response.status_code == 200, response.text
        value = response.json()
        if value["status"] in {"completed", "failed", "cancelled", "interrupted", "acknowledged"}:
            return value
        await asyncio.sleep(0.01)
    raise AssertionError("AI test request did not reach terminal state")


async def test_token_required_and_no_token_never_exposes_api(tmp_path):
    async with running(tmp_path) as (client, _):
        assert (await client.get("/health", headers={"X-Service-Token": "wrong"})).status_code == 200
        assert (await client.get("/ai/v1/profiles", headers={"X-Service-Token": "wrong"})).status_code == 401
    async with running(tmp_path, token="") as (client, _):
        assert (await client.get("/ai/v1/profiles")).status_code == 503


async def test_missing_keys_are_unconfigured_and_do_not_create_requests(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    async with running(tmp_path, seed=True) as (client, _):
        profiles = (await client.get("/ai/v1/profiles")).json()
        assert len(profiles) == 3
        assert all(not item["configured"] for item in profiles)
        response = await submit(client, profile_id="deepseek-default")
        assert response.status_code == 400
        assert (await client.get("/ai/v1/requests/request-1")).status_code == 404


async def test_credentials_encrypted_masked_and_removed_with_profile(tmp_path):
    async with running(tmp_path) as (client, app):
        profile = await add_profile(client)
        assert profile["configured"] is True and profile["has_api_key"] is True
        assert SECRET not in json.dumps(profile)
        response = await client.patch("/ai/v1/profiles/test-model", json={"name": "改名"})
        assert response.json()["version"] == 2
        versions = (await client.get("/ai/v1/profiles/test-model/versions")).json()
        assert [item["version"] for item in versions] == [2, 1]
        assert SECRET not in json.dumps(versions)
        assert SECRET.encode() not in app.state.store.path.read_bytes()
        private = app.state.store.profile("test-model", 1, private=True)
        assert private["api_key"] == SECRET
        assert (await client.delete("/ai/v1/profiles/test-model")).status_code == 200
        assert app.state.store.profile("test-model", 1, private=True)["api_key"] is None
        assert (app.state.store.directory / "encryption.key").stat().st_mode & 0o777 == 0o600


async def test_profile_validation_never_echoes_key(tmp_path):
    async with running(tmp_path) as (client, _):
        for patch in (
            {"base_url": "https://user:password@provider.test"},
            {"parameters": {"headers": {"Authorization": SECRET}}},
            {"api_key": SECRET * 1000},
        ):
            response = await client.post("/ai/v1/profiles", json=profile_body(**patch))
            assert response.status_code == 422
            assert SECRET not in response.text


async def test_idempotency_ack_and_changed_payload_conflict(tmp_path):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=completion())

    async with running(tmp_path, handler) as (client, app):
        await add_profile(client)
        assert (await submit(client)).status_code == 202
        assert (await finished(client))["result"]["text"] == "测试结果"
        assert (await submit(client)).json()["status"] == "completed"
        assert len(calls) == 1
        assert (await submit(client, prompt="different")).status_code == 409
        response = await client.post("/ai/v1/requests/request-1/ack")
        assert response.json()["status"] == "acknowledged"
        assert response.json()["result"] is None
        assert app.state.store.payload("request-1") is None
        assert (await submit(client)).json()["status"] == "acknowledged"
        assert len(calls) == 1
        assert [event["event"] for event in app.state.store.events("request-1")] == ["acknowledged"]


async def test_profile_snapshot_and_optimistic_edit(tmp_path):
    calls = []

    def handler(request):
        calls.append((json.loads(request.content), request.headers["Authorization"]))
        return httpx.Response(200, json=completion())

    async with running(tmp_path, handler) as (client, _):
        await add_profile(client)
        update = await client.patch(
            "/ai/v1/profiles/test-model", json={"model": "test-model-v2", "api_key": "new-test-secret"}
        )
        assert update.json()["version"] == 2
        conflict = await client.patch(
            "/ai/v1/profiles/test-model", json={"name": "bad", "expected_version": 1}
        )
        assert conflict.status_code == 409
        await submit(client, profile_version=1)
        assert (await finished(client))["profile_version"] == 1
        assert calls[0][0]["model"] == "test-model-v1"
        assert calls[0][1] == "Bearer " + SECRET


async def test_cancel_and_delete_during_provider_request(tmp_path):
    entered = asyncio.Event()

    async def handler(request):
        entered.set()
        await asyncio.sleep(30)
        return httpx.Response(200, json=completion())

    async with running(tmp_path, handler) as (client, app):
        await add_profile(client)
        await submit(client)
        await asyncio.wait_for(entered.wait(), 2)
        assert (await client.delete("/ai/v1/profiles/test-model")).status_code == 409
        assert (await client.post("/ai/v1/requests/request-1/ack")).status_code == 409
        cancelled = await client.post("/ai/v1/requests/request-1/cancel")
        assert cancelled.json()["status"] == "cancelled"
        assert app.state.store.find_request("request-1")["result"] is None
        assert (await client.delete("/ai/v1/requests/request-1")).json()["purged"] is True
        assert app.state.store.payload("request-1") is None


async def test_restart_marks_inflight_interrupted_without_provider_replay(tmp_path):
    store = Store(tmp_path / "ai")
    store.save_profile(profile_body())
    payload = {
        "request_id": "orphan",
        "operation": "generate",
        "profile_id": "test-model",
        "prompt": "private",
    }
    store.create_request(payload, 1, Store.fingerprint(payload))
    store.transition("orphan", "running")

    def handler(request):
        raise AssertionError("Interrupted requests must never be replayed automatically")

    async with running(tmp_path, handler) as (client, app):
        result = (await client.get("/ai/v1/requests/orphan")).json()
        assert result["status"] == "interrupted"
        assert result["error"]["code"] == "service_interrupted"
        assert not app.state.runtime.tasks


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "provider_rejected"),
        (401, "authentication_failed"),
        (403, "authentication_failed"),
        (402, "quota_exhausted"),
        (404, "model_or_endpoint_missing"),
        (429, "rate_limited"),
        (500, "provider_unavailable"),
    ],
)
async def test_provider_errors_sanitized_and_not_retried(tmp_path, status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": SECRET + " private input"}})

    async with running(tmp_path, handler) as (client, _):
        await add_profile(client)
        await submit(client)
        result = await finished(client)
        assert result["status"] == "failed" and result["error"]["code"] == code
        assert SECRET not in json.dumps(result)
        assert len(calls) == 1


@pytest.mark.parametrize(
    "text,expected", [("not json", "invalid_json"), ('{"wrong": 1}', "schema_validation_failed")]
)
async def test_schema_failures_not_fake_success(tmp_path, text, expected):
    async with running(tmp_path, lambda request: httpx.Response(200, json=completion(text))) as (client, _):
        await add_profile(client)
        schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
        await submit(client, output_schema=schema)
        result = await finished(client)
        assert result["status"] == "failed"
        assert result["error"]["code"] == expected
        assert result["result"] is None


async def test_schema_success_and_remote_reference_rejected(tmp_path):
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=completion('{"answer": "yes"}'))

    async with running(tmp_path, handler) as (client, _):
        await add_profile(client)
        schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
        await submit(client, output_schema=schema)
        result = await finished(client)
        assert result["result"]["json"] == {"answer": "yes"}
        assert calls[0]["response_format"] == {"type": "json_object"}
        assert "JSON Schema" in calls[0]["messages"][0]["content"]
        assert (
            await submit(client, request_id="remote", output_schema={"$ref": "https://private.test/schema"})
        ).status_code == 422
        assert len(calls) == 1


async def test_provider_connection_test_is_real_and_no_fake_success(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": SECRET}})

    async with running(tmp_path, handler) as (client, _):
        await add_profile(client)
        response = await client.post("/ai/v1/profiles/test-model/test")
        assert response.status_code == 502 and response.json()["ok"] is False
        assert SECRET not in response.text
        assert len(calls) == 1
        status = (await client.get("/ai/v1/profiles/test-model")).json()
        assert status["test_status"] == "failed" and status["last_test_error"] == "authentication_failed"
        changed = (await client.patch("/ai/v1/profiles/test-model", json={"name": "新配置版本"})).json()
        assert changed["test_status"] == "untested" and changed["last_test_at"] is None


async def test_generation_with_images_rejects_text_only_model(tmp_path):
    async with running(tmp_path) as (client, _):
        await add_profile(client)
        response = await submit(
            client,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}],
                }
            ],
        )
        assert response.status_code == 422


async def test_embedding_batching_keeps_order_and_aggregates_usage(tmp_path):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/embeddings"
        assert body["encoding_format"] == "float"
        calls.append(body)
        items = [
            {"index": index, "embedding": [float(text), 1.0]} for index, text in enumerate(body["input"])
        ]
        return httpx.Response(
            200,
            json={
                "data": list(reversed(items)),
                "model": "embed-model",
                "usage": {"prompt_tokens": len(items), "total_tokens": len(items)},
            },
        )

    async with running(tmp_path, handler) as (client, _):
        await add_profile(
            client, capabilities={"embedding": True, "stream": False}, parameters={"embedding_batch_size": 10}
        )
        response = await submit(client, operation="embed", prompt=None, texts=[str(i) for i in range(12)])
        assert response.status_code == 202, response.text
        result = await finished(client)
        assert result["status"] == "completed", result
        assert [len(item["input"]) for item in calls] == [10, 2]
        assert [vector[0] for vector in result["result"]["vectors"]] == list(range(12))
        assert result["usage"]["prompt_tokens"] == 12
        assert result["usage"]["provider_calls"] == 2


@pytest.mark.parametrize("vectors", [[], [[1.0], [2.0, 3.0]], [[float("inf")], [1.0]]])
async def test_invalid_embeddings_rejected(tmp_path, vectors):
    def handler(request):
        return httpx.Response(
            200,
            content=json.dumps(
                {"data": [{"index": i, "embedding": vector} for i, vector in enumerate(vectors)]}
            ),
        )

    async with running(tmp_path, handler) as (client, _):
        await add_profile(client, capabilities={"embedding": True, "stream": False})
        await submit(client, operation="embed", prompt=None, texts=["one", "two"])
        result = await finished(client)
        assert result["status"] == "failed"
        assert result["error"]["code"] == "invalid_embeddings"


async def test_ollama_profiles_can_be_local_without_api_key(tmp_path):
    async with running(tmp_path) as (client, _):
        result = await add_profile(client, protocol="ollama", base_url="http://127.0.0.1:11434", api_key=None)
        assert result["configured"] is True and result["has_api_key"] is False


async def test_env_credentials_only_fill_unmodified_templates(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    async with running(tmp_path, seed=True) as (client, _):
        templates = (await client.get("/ai/v1/profiles")).json()
        deepseek = next(item for item in templates if item["id"] == "deepseek-default")
        assert deepseek["capabilities"]["vision"] is True
        assert "保守" in deepseek["configuration_notice"]
        await client.patch("/ai/v1/profiles/dashscope-default", json={"name": "用户改过的模型"})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "new-env-test-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "another-env-test-key")
    async with running(tmp_path, seed=True) as (client, _):
        deepseek = (await client.get("/ai/v1/profiles/deepseek-default")).json()
        changed = (await client.get("/ai/v1/profiles/dashscope-default")).json()
        assert deepseek["configured"] is True and deepseek["version"] == 2
        assert deepseek["credential_source"] == "environment"
        assert "new-env-test-key" not in json.dumps(deepseek)
        assert changed["configured"] is False and changed["name"] == "用户改过的模型"


async def test_only_one_service_can_own_ai_data_dir(tmp_path):
    async with running(tmp_path) as (client, app):
        await add_profile(client)
        with pytest.raises(RuntimeError, match="已有服务运行"):
            async with running(tmp_path):
                pass
        assert (await client.get("/ai/v1/profiles")).status_code == 200
        assert app.state.store.profile("test-model") is not None


async def test_sse_history_supports_reconnect_cursor(tmp_path):
    async with running(tmp_path) as (client, app):
        await add_profile(client)
        await submit(client)
        await finished(client)
        events = app.state.store.events("request-1")
        assert [event["event"] for event in events] == ["started", "text_delta", "completed"]
        response = await client.get(
            "/ai/v1/requests/request-1/events", headers={"Last-Event-ID": str(events[1]["id"])}
        )
        assert response.status_code == 200
        assert "event: completed" in response.text
        assert "event: started" not in response.text and "event: text_delta" not in response.text


async def test_provider_private_error_content_is_not_in_logs(tmp_path, caplog):
    def handler(request):
        return httpx.Response(500, json={"error": {"message": SECRET, "request": "PRIVATE_BOOK_PASSAGE"}})

    async with running(tmp_path, handler) as (client, _):
        await add_profile(client)
        await submit(client)
        result = await finished(client)
        assert result["status"] == "failed"
        await client.post("/ai/v1/profiles/test-model/test")
        assert SECRET not in caplog.text and "PRIVATE_BOOK_PASSAGE" not in caplog.text
        assert SECRET not in json.dumps(result) and "PRIVATE_BOOK_PASSAGE" not in json.dumps(result)


async def test_provider_malformed_object_returns_clear_error(tmp_path):
    async with running(tmp_path, lambda request: httpx.Response(200, json=[SECRET])) as (client, _):
        await add_profile(client)
        await submit(client)
        result = await finished(client)
        assert result["status"] == "failed" and result["error"]["code"] == "invalid_provider_response"
        response = await client.post("/ai/v1/profiles/test-model/test")
        assert response.status_code == 502 and SECRET not in response.text


async def test_new_requests_do_not_use_disabled_profile_even_with_old_version(tmp_path):
    async with running(tmp_path) as (client, _):
        await add_profile(client)
        await client.patch("/ai/v1/profiles/test-model", json={"enabled": False})
        assert (await submit(client, profile_version=1)).status_code == 400


async def test_atomic_duplicate_submission_calls_provider_once(tmp_path):
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0.03)
        return httpx.Response(200, json=completion())

    async with running(tmp_path, handler) as (client, _):
        await add_profile(client)
        responses = await asyncio.gather(*(submit(client) for _ in range(6)))
        assert all(response.status_code == 202 for response in responses)
        assert (await finished(client))["status"] == "completed"
        assert len(calls) == 1


async def test_settings_form_output_limit_is_valid_and_request_can_override(tmp_path):
    limits = []

    def handler(request):
        limits.append(json.loads(request.content)["max_tokens"])
        return httpx.Response(200, json=completion())

    async with running(tmp_path, handler) as (client, _):
        await add_profile(client, parameters={"max_tokens": 2048, "temperature": 1})
        await submit(client)
        assert (await finished(client))["status"] == "completed"
        await submit(client, request_id="override-limit", max_tokens=1024)
        assert (await finished(client, "override-limit"))["status"] == "completed"
        assert limits == [2048, 1024]
