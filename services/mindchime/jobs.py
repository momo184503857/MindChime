"""Durable business jobs. Model execution lives in the separate AI service."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from typing import Any, Awaitable, Callable

import httpx

from .db import db

HANDLERS: dict[str, Callable[..., Awaitable[Any]]] = {}
TERMINAL = {"completed", "partial", "failed", "cancelled"}
ACTIVE = {"queued", "running", "pause_requested", "paused", "waiting_error", "interrupted"}
AI_URL = os.getenv("MINDCHIME_AI_URL", f"http://127.0.0.1:{os.getenv('MINDCHIME_AI_PORT', '8766')}").rstrip("/")


class JobControl(Exception):
    def __init__(self, status: str):
        self.status = status
        super().__init__(status)


class StepFailure(Exception):
    pass


def register_handler(kind: str, handler: Callable[..., Awaitable[Any]]) -> None:
    HANDLERS[kind] = handler


def emit_job(job: dict) -> None:
    keys = {"kind", "stage", "completed", "total", "position", "round", "current_agent_id", "current_agent_name", "error", "warning", "retrieval_mode", "stop_reason"}
    event = {k: job[k] for k in ("id", "kind", "title", "status", "version", "created_at", "updated_at")}
    event["data"] = {k: v for k, v in job["data"].items() if k in keys}
    db.emit("jobs", "job", event)
    db.emit(f"job:{job['id']}", "job", event)
    cid = job["data"].get("input", {}).get("conversation_id")
    if cid:
        db.emit(f"conversation:{cid}", "job", event)


def enqueue(kind: str, payload: dict, request_id: str | None = None) -> dict:
    fingerprint = hashlib.sha256(json.dumps([kind, payload], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if request_id:
        for old in db.list("job"):
            if old["data"].get("request_id") == request_id:
                if old["data"].get("fingerprint") != fingerprint:
                    raise ValueError("同一请求标识对应不同内容，请重新提交。")
                return old
    cid = payload.get("conversation_id")
    if cid:
        for old in db.list("job"):
            if old["status"] in ACTIVE and old["data"].get("input", {}).get("conversation_id") == cid:
                raise ValueError("此会话已有未结束任务，请先继续或结束它。")
    job = db.create("job", kind, {"kind": kind, "input": payload, "request_id": request_id,
                    "model_routes": settings(),
                    "fingerprint": fingerprint, "steps": {}, "attempt": 0, "stage": "等待处理"}, status="queued")
    emit_job(job)
    return job


def settings() -> dict:
    records = db.list("settings")
    return records[0]["data"] if records else {}


def ai_headers() -> dict:
    return {"X-Service-Token": os.getenv("MINDCHIME_AI_TOKEN", "")}


class Ctx:
    def __init__(self, job: dict, stop: asyncio.Event | None = None):
        self.id = job["id"]
        self.stop = stop or asyncio.Event()
        self.partial_output = None

    @property
    def job(self) -> dict:
        return db.get(self.id, "job")

    def progress(self, stage: str, **fields: Any) -> None:
        emit_job(db.update(self.id, data={"stage": stage, **fields}))

    def check_control(self) -> None:
        status = self.job["status"]
        if status in {"cancelled", "deleted"}:
            raise JobControl("cancelled")
        if self.stop.is_set():
            raise JobControl("interrupted")
        if status in {"pause_requested", "paused"}:
            raise JobControl("paused")

    async def generate(self, prompt: str, *, purpose: str = "chat", messages: list | None = None,
                       schema: dict | None = None, step_key: str, profile_id: str | None = None) -> Any:
        result = await self._call("generate", purpose, step_key, profile_id, prompt=prompt,
                                  messages=messages, output_schema=schema)
        if schema is not None:
            value = result.get("json")
            if value is None:
                try:
                    value = json.loads(result.get("text", ""))
                except (ValueError, TypeError) as exc:
                    raise StepFailure("模型未返回可用的结构化内容，请检查模型能力或重试。") from exc
            return value
        return result.get("text", "")

    async def embed(self, texts: list[str], *, step_key: str, profile_id: str | None = None) -> list[list[float]]:
        result = await self._call("embed", "embedding", step_key, profile_id, texts=texts)
        return result["vectors"]

    async def pin_profile(self, profile_id):
        pinned = self.job["data"].get("profile_snapshots", {})
        if profile_id not in pinned:
            async with httpx.AsyncClient(base_url=AI_URL, headers=ai_headers(), timeout=15, trust_env=False) as client:
                response = await client.get("/ai/v1/profiles")
                response.raise_for_status()
            for profile in response.json():
                pinned.setdefault(profile["id"], profile["version"])
            db.update(self.id, data={"profile_snapshots": pinned})
        if profile_id not in pinned:
            raise StepFailure("所选模型配置已不存在，请重新配置。")
        return pinned[profile_id]

    async def _call(self, operation: str, purpose: str, step_key: str, profile_id: str | None, **kwargs: Any) -> dict:
        self.check_control()
        job = self.job
        steps = job["data"].get("steps", {})
        cached = steps.get(step_key, {})
        if cached.get("status") == "completed":
            return cached["result"]
        profile_id = profile_id or job["data"]["input"].get("model_profile_id")
        config = job["data"].get("model_routes", settings())
        profile_id = profile_id or config.get("purpose_profiles", {}).get(purpose) or config.get("default_profile_id")
        if not profile_id:
            raise StepFailure(f"尚未配置 {purpose} 模型，请在模型设置中选择可用服务。")
        attempt = job["data"].get("attempt", 0)
        new_request_id = hashlib.sha256(f"{self.id}:{step_key}:{attempt}".encode()).hexdigest()
        request_id = cached.get("request_id") or new_request_id
        # An in-flight request after a process restart is deliberately not silently replayed.
        if cached.get("status") == "running" and cached.get("attempt") == attempt:
            raise StepFailure("上次模型调用状态未确定，请明确重试后恢复；不会自动重复调用。")
        request_ids = list(dict.fromkeys(cached.get("request_ids", []) + ([cached["request_id"]] if cached.get("request_id") else [])))
        steps[step_key] = {"request_id": request_id, "request_ids": request_ids, "status": "running", "attempt": attempt, "profile_id": profile_id}
        db.update(self.id, data={"steps": steps, "active_step": step_key})
        body = {"request_id": request_id, "operation": operation, "profile_id": profile_id,
                "prompt_version": "mindchime-v1", **{k: v for k, v in kwargs.items() if v is not None}}
        async with httpx.AsyncClient(base_url=AI_URL, headers=ai_headers(), timeout=30, trust_env=False) as client:
            relay_task = None
            try:
                pinned = self.job["data"].get("profile_snapshots", {})
                if profile_id not in pinned:
                    profiles_response = await client.get("/ai/v1/profiles")
                    profiles_response.raise_for_status()
                    # Snapshot all available configurations together so later roles cannot drift mid-task.
                    for profile in profiles_response.json():
                        pinned.setdefault(profile["id"], profile["version"])
                    db.update(self.id, data={"profile_snapshots": pinned})
                if profile_id not in pinned:
                    raise StepFailure("所选模型配置已不存在，请重新配置。")
                body["profile_version"] = pinned[profile_id]
                recovered_state = None
                if cached.get("request_id") and cached.get("status") != "invalid":
                    previous = await client.get(f"/ai/v1/requests/{cached['request_id']}")
                    if previous.status_code != 404:
                        previous.raise_for_status()
                        state = previous.json()
                        if state["status"] in {"completed", "queued", "running", "pending"}:
                            recovered_state = state
                        elif state["status"] == "acknowledged":
                            raise StepFailure("原请求已清除但本地结果缺失，请先检查数据恢复情况，不会自动重复调用。")
                if recovered_state is None:
                    request_id = new_request_id
                    body["request_id"] = request_id
                    response = await client.post("/ai/v1/requests", json=body)
                    response.raise_for_status()
                    submitted = response.json()
                    request_id = submitted.get("id", request_id)
                steps[step_key]["request_id"] = request_id
                steps[step_key]["request_ids"] = list(dict.fromkeys(request_ids + [request_id]))
                db.update(self.id, data={"steps": steps})
                cid = job["data"]["input"].get("conversation_id")
                if cid and operation == "generate":
                    relay_task = asyncio.create_task(self._relay(request_id, cid, step_key, kwargs.get("output_schema")))
                while True:
                    latest = self.job
                    if self.stop.is_set() or latest["status"] == "cancelled":
                        try:
                            await client.post(f"/ai/v1/requests/{request_id}/cancel")
                        finally:
                            raise JobControl("interrupted" if self.stop.is_set() else "cancelled")
                    if recovered_state is not None:
                        state, recovered_state = recovered_state, None
                    else:
                        response = await client.get(f"/ai/v1/requests/{request_id}")
                        response.raise_for_status()
                        state = response.json()
                    if state["status"] == "completed":
                        result = state.get("result") or {}
                        if self.stop.is_set() or self.job["status"] == "cancelled":
                            raise JobControl("interrupted" if self.stop.is_set() else "cancelled")
                        current = self.job["data"].get("steps", {})
                        current[step_key] = {**steps[step_key], "status": "completed", "result": result,
                                             "usage": state.get("usage"), "profile_version": state.get("profile_version")}
                        db.update(self.id, data={"steps": current, "active_step": None})
                        try:
                            await client.post(f"/ai/v1/requests/{request_id}/ack")
                        except httpx.HTTPError:
                            pass  # Cleanup is retried on source deletion; results are already durable.
                        return result
                    if state["status"] in {"failed", "cancelled", "interrupted", "acknowledged"}:
                        error = state.get("error") or f"模型任务状态：{state['status']}"
                        raise StepFailure(str(error))
                    await asyncio.sleep(0.25)
            except JobControl:
                db.update(self.id, data={"active_step": None})
                raise
            except (httpx.HTTPError, StepFailure) as exc:
                error = error_description(exc)
                current = self.job["data"].get("steps", {})
                current[step_key] = {**steps[step_key], "status": "failed", "error": error}
                db.update(self.id, data={"steps": current, "error": error, "failed_step": step_key})
                if isinstance(exc, httpx.HTTPStatusError):
                    try:
                        detail = exc.response.json().get("detail", "模型服务请求失败")
                    except ValueError:
                        detail = "模型服务请求失败"
                    raise StepFailure(str(detail)) from exc
                raise StepFailure(error) from exc
            finally:
                if relay_task:
                    try:
                        await asyncio.wait_for(asyncio.shield(relay_task), timeout=.5)
                    except (asyncio.TimeoutError, httpx.HTTPError):
                        relay_task.cancel()

    async def _relay(self, request_id, cid, step_key, schema):
        raw, emitted = "", ""
        event_type = ""
        try:
            async with httpx.AsyncClient(base_url=AI_URL, headers=ai_headers(), timeout=httpx.Timeout(10, read=None), trust_env=False) as client:
                async with client.stream("GET", f"/ai/v1/requests/{request_id}/events") as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("event:"):
                            event_type = line[6:].strip()
                        elif line.startswith("data:"):
                            try:
                                item = json.loads(line[5:].strip())
                            except ValueError:
                                continue
                            event = item.get("event", event_type)
                            value = item.get("data", item)
                            if event == "text_delta":
                                raw += value.get("text", "")
                                if schema and "text" in schema.get("properties", {}):
                                    current = partial_json_text(raw)
                                elif schema:
                                    continue
                                else:
                                    current = raw
                                delta = current[len(emitted):] if current.startswith(emitted) else ""
                                if delta:
                                    data = self.job["data"]
                                    db.emit(f"conversation:{cid}", "text_delta", {"text": delta, "agent_id": data.get("current_agent_id"),
                                        "agent_name": data.get("current_agent_name"), "job_id": self.id, "step_key": step_key})
                                    emitted = current
                                    if schema and "text" in schema.get("properties", {}):
                                        self.partial_output = {"text": current, "step_key": step_key, "agent_id": data.get("current_agent_id"), "speaker_name": data.get("current_agent_name")}
                            elif event in {"completed", "failed", "cancelled", "interrupted"}:
                                return
        except (httpx.HTTPError, asyncio.CancelledError):
            return


def partial_json_text(raw):
    """Expose only the user-facing text string, never streamed JSON control fields."""
    match = re.search(r'"text"\s*:\s*"', raw)
    if not match:
        return ""
    text = raw[match.end():]
    output, index = [], 0
    escapes = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f"}
    while index < len(text):
        char = text[index]
        if char == '"':
            break
        if char != "\\":
            output.append(char)
            index += 1
            continue
        if index+1 >= len(text):
            break
        nxt = text[index+1]
        if nxt == "u":
            if index+6 > len(text):
                break
            try:
                output.append(chr(int(text[index+2:index+6], 16)))
            except ValueError:
                break
            index += 6
        else:
            output.append(escapes.get(nxt, nxt))
            index += 2
    return "".join(output)


def error_description(exc):
    if isinstance(exc, httpx.TimeoutException):
        return f"{type(exc).__name__}：AI 服务响应超时，原调用可能已完成。请点击重试/恢复，系统会先查询并收回原请求结果，不自动重复调用。"
    return str(exc).strip() or f"{type(exc).__name__}：处理被中断，请查看任务状态后恢复。"


async def purge_ai_requests(job: dict) -> bool:
    ok = True
    async with httpx.AsyncClient(base_url=AI_URL, headers=ai_headers(), timeout=10, trust_env=False) as client:
        request_ids = {rid for step in job["data"].get("steps", {}).values() for rid in step.get("request_ids", []) + ([step["request_id"]] if step.get("request_id") else [])}
        for request_id in request_ids:
            if request_id:
                try:
                    response = await client.delete(f"/ai/v1/requests/{request_id}")
                    if response.status_code not in {200, 204, 404}:
                        ok = False
                except httpx.HTTPError:
                    ok = False
    return ok

