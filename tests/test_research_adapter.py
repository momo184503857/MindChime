import json

import httpx
from ai_service.app import create_app
from ai_service.research import public_url
from fastapi.testclient import TestClient


def test_research_credentials_limits_encryption_and_request_receipts(tmp_path):
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append((request.url.path, payload))
        if request.url.path == "/search":
            assert payload["max_results"] == 5
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"url": "https://example.com/a", "title": "正文来源", "content": "搜索摘要"},
                        {"url": "http://127.0.0.1/private", "content": "不能采集"},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [{"url": "https://example.com/a", "raw_content": "可追溯的真实网页正文"}],
                "failed_results": [{"url": "https://example.com/failure", "error": "missing"}],
            },
        )

    app = create_app(
        data_dir=tmp_path, service_token="local-service", transport=httpx.MockTransport(handler), seed=False
    )
    with TestClient(app) as client:
        headers = {"X-Service-Token": "local-service"}
        assert client.get("/ai/v1/research/config").status_code == 401
        assert client.get("/ai/v1/research/config", headers=headers).json()["configured"] is False
        missing = client.post(
            "/ai/v1/research/search", headers=headers, json={"request_id": "missing", "query": "人物"}
        )
        assert missing.status_code == 409 and seen == []
        configured = client.patch(
            "/ai/v1/research/config", headers=headers, json={"api_key": "test-search-secret", "enabled": True}
        ).json()
        assert configured["configured"] and "api_key" not in configured
        payload = {"request_id": "search-once", "config_version": 1, "query": "人物著作", "max_results": 99}
        first = client.post("/ai/v1/research/search", headers=headers, json=payload)
        assert first.status_code == 200 and len(first.json()["results"]) == 1
        second = client.post("/ai/v1/research/search", headers=headers, json=payload)
        assert second.json() == first.json() and len(seen) == 1
        assert (
            client.post(
                "/ai/v1/research/search", headers=headers, json={**payload, "query": "不同输入"}
            ).status_code
            == 409
        )
        result = client.post(
            "/ai/v1/research/extract",
            headers=headers,
            json={
                "request_id": "extract",
                "config_version": 1,
                "urls": ["https://example.com/a", "http://127.0.0.1/secret"],
            },
        )
        assert result.status_code == 200
        assert seen[-1][1]["urls"] == ["https://example.com/a"]
        assert result.json()["failed_results"][0]["error"] == "正文提取失败"
        assert "test-search-secret" not in (tmp_path / "ai" / "ai.sqlite3").read_bytes().decode(
            errors="ignore"
        )


def test_uncertain_failed_research_is_not_automatically_replayed(tmp_path):
    seen = []

    def handler(request):
        seen.append(1)
        return httpx.Response(503, json={"error": "upstream"})

    app = create_app(
        data_dir=tmp_path, service_token="service", transport=httpx.MockTransport(handler), seed=False
    )
    with TestClient(app) as client:
        headers = {"X-Service-Token": "service"}
        client.patch("/ai/v1/research/config", headers=headers, json={"api_key": "test-key"})
        payload = {"request_id": "same-attempt", "query": "人物"}
        assert client.post("/ai/v1/research/search", headers=headers, json=payload).status_code == 502
        assert client.post("/ai/v1/research/search", headers=headers, json=payload).status_code == 409
        assert len(seen) == 1
        assert (
            client.post(
                "/ai/v1/research/search",
                headers=headers,
                json={**payload, "request_id": "explicit-new-attempt"},
            ).status_code
            == 502
        )
        assert len(seen) == 2


def test_public_research_url_boundary():
    for url in (
        "file:///etc/passwd",
        "http://localhost/a",
        "http://127.0.0.1/a",
        "http://[::1]/a",
        "http://10.0.0.1/a",
        "https://u:p@example.com",
    ):
        assert not public_url(url)
    assert public_url("https://example.com/a")


def test_research_acknowledgment_purges_results_and_prevents_replay(tmp_path):
    seen = []

    def handler(request):
        seen.append(1)
        return httpx.Response(200, json={"results": [{"url": "https://example.com", "title": "正文"}]})

    app = create_app(
        data_dir=tmp_path, service_token="service", transport=httpx.MockTransport(handler), seed=False
    )
    with TestClient(app) as client:
        headers = {"X-Service-Token": "service"}
        client.patch("/ai/v1/research/config", headers=headers, json={"api_key": "key"})
        payload = {"request_id": "saved", "query": "人物"}
        assert client.post("/ai/v1/research/search", headers=headers, json=payload).status_code == 200
        assert client.delete("/ai/v1/research/requests/saved", headers=headers).status_code == 200
        assert client.post("/ai/v1/research/search", headers=headers, json=payload).status_code == 409
        assert len(seen) == 1
        client.delete("/ai/v1/research/requests/not-started", headers=headers)
        assert (
            client.post(
                "/ai/v1/research/search", headers=headers, json={**payload, "request_id": "not-started"}
            ).status_code
            == 409
        )
        assert len(seen) == 1
        with app.state.store.connection() as conn:
            assert conn.execute("SELECT result FROM research_requests WHERE id='saved'").fetchone()[0] is None
