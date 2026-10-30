"""Optional bounded research adapter; credentials/results stay inside the AI service."""

import hashlib
import ipaddress
import json
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, Request


def public_url(value):
    try:
        parsed = urlparse(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return False
        if parsed.hostname.lower() in {
            "localhost",
            "localhost.localdomain",
        } or parsed.hostname.lower().endswith((".local", ".internal", ".localhost")):
            return False
        try:
            return ipaddress.ip_address(parsed.hostname).is_global
        except ValueError:
            return "." in parsed.hostname
    except (ValueError, TypeError):
        return False


def install(application, dependencies):
    def setup(store):
        with store.connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS research_config (version INTEGER PRIMARY KEY, encrypted TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS research_requests (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT)"
            )

    def config(request, version=None):
        store = request.app.state.store
        setup(store)
        with store.connection() as conn:
            row = (
                conn.execute(
                    "SELECT version,encrypted FROM research_config WHERE version=?", (version,)
                ).fetchone()
                if version
                else conn.execute(
                    "SELECT version,encrypted FROM research_config ORDER BY version DESC LIMIT 1"
                ).fetchone()
            )
        return (row["version"], store.decrypt(row["encrypted"])) if row else (0, {})

    @application.get("/ai/v1/research/config", dependencies=dependencies)
    def get_config(request: Request):
        version, value = config(request)
        return {
            "provider": "tavily",
            "version": version,
            "configured": bool(value.get("api_key")),
            "enabled": value.get("enabled", True),
        }

    @application.patch("/ai/v1/research/config", dependencies=dependencies)
    def save_config(body: dict, request: Request):
        version, value = config(request)
        key = body.get("api_key", value.get("api_key", ""))
        if not isinstance(key, str) or len(key) > 8192:
            raise HTTPException(422, "搜索凭据无效")
        value = {"api_key": key, "enabled": bool(body.get("enabled", value.get("enabled", True)))}
        store = request.app.state.store
        with store.connection() as conn:
            conn.execute("INSERT INTO research_config VALUES (?,?)", (version + 1, store.encrypt(value)))
        return get_config(request)

    @application.delete("/ai/v1/research/requests/{id}", dependencies=dependencies)
    def acknowledge_research(id: str, request: Request):
        store = request.app.state.store
        setup(store)
        with store.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO research_requests VALUES (?, '', 'acknowledged', NULL)", (id,)
            )
            conn.execute("UPDATE research_requests SET status='acknowledged',result=NULL WHERE id=?", (id,))
        return {"acknowledged": True}

    @application.post("/ai/v1/research/{operation}", dependencies=dependencies)
    async def research(operation: str, body: dict, request: Request):
        version, value = config(request, body.get("config_version"))
        if not value.get("api_key") or not value.get("enabled", True):
            raise HTTPException(409, "请先由管理员配置并启用搜索服务")
        if operation not in {"search", "extract"}:
            raise HTTPException(404, "未知搜索操作")
        rid = str(body.get("request_id", ""))
        if not rid or len(rid) > 200:
            raise HTTPException(422, "缺少有效请求编号")
        payload = (
            {
                "query": str(body.get("query", ""))[:1000],
                "max_results": min(5, max(1, int(body.get("max_results", 5)))),
                "search_depth": "basic",
                "include_answer": False,
                "include_raw_content": False,
            }
            if operation == "search"
            else {
                "urls": [u for u in body.get("urls", [])[:20] if public_url(u)],
                "format": "markdown",
                "extract_depth": "basic",
            }
        )
        fingerprint = hashlib.sha256(
            json.dumps([operation, payload, version], sort_keys=True).encode()
        ).hexdigest()
        store = request.app.state.store
        with store.connection() as conn:
            old = conn.execute("SELECT * FROM research_requests WHERE id=?", (rid,)).fetchone()
            if old:
                if old["fingerprint"] != fingerprint:
                    raise HTTPException(409, "搜索请求编号对应不同输入")
                if old["status"] == "completed":
                    return store.decrypt(old["result"])
                raise HTTPException(409, "先前搜索调用状态未确定或失败，请明确重试后提交新尝试")
            conn.execute("INSERT INTO research_requests VALUES (?,?,?,NULL)", (rid, fingerprint, "running"))
        try:
            client = request.app.state.runtime.adapters.client
            response = await client.post(
                "https://api.tavily.com/" + operation,
                json=payload,
                headers={"Authorization": "Bearer " + value["api_key"]},
                timeout=60,
            )
            response.raise_for_status()
            result = response.json()
            if operation == "search":
                result = {
                    "results": [
                        {"url": r["url"], "title": r.get("title", ""), "content": r.get("content", "")}
                        for r in result.get("results", [])
                        if public_url(r.get("url"))
                    ][:5],
                    "usage": result.get("usage"),
                    "config_version": version,
                }
            else:
                result = {
                    "results": [
                        {"url": r["url"], "raw_content": r.get("raw_content", "")}
                        for r in result.get("results", [])
                        if public_url(r.get("url"))
                    ],
                    "failed_results": [
                        {"url": r.get("url"), "error": "正文提取失败"}
                        for r in result.get("failed_results", [])
                    ],
                    "usage": result.get("usage"),
                    "config_version": version,
                }
            with store.connection() as conn:
                conn.execute(
                    "UPDATE research_requests SET status='completed',result=? WHERE id=? AND status='running'",
                    (store.encrypt(result), rid),
                )
            return result
        except (httpx.HTTPError, ValueError, KeyError):
            with store.connection() as conn:
                conn.execute(
                    "UPDATE research_requests SET status='failed' WHERE id=? AND status='running'", (rid,)
                )
            raise HTTPException(502, "搜索服务调用失败，请检查凭据、额度和网络后明确重试") from None
