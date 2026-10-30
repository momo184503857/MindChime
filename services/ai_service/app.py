"""Run with `uvicorn ai_service.app:app --host 127.0.0.1 --port 8766`.

The application owns only AI configuration and requests. It never imports business modules.
"""

import asyncio
import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from jsonschema import FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for

from .adapters import Adapters, ProviderError, checked_messages, validate_profile
from .schemas import AIRequest, ProfileCreate, ProfilePatch
from .store import TERMINAL, ConflictError, Store, single_instance

logger = logging.getLogger("mindchime.ai")


def default_profiles(store):
    templates = [
        {
            "id": "deepseek-default",
            "name": "DeepSeek 官方 · 对话与分析",
            "protocol": "openai_chat",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-flash",
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "capabilities": {
                "stream": True,
                "vision": True,
                "json": True,
                "embedding": False,
                "context_tokens": 128000,
            },
            "parameters": {"thinking": {"type": "disabled"}},
            "enabled": True,
            "configuration_notice": "DeepSeek Flash 支持图像输入；128k 为本地保守上下文配置，可按实际模型调整。",
        },
        {
            "id": "dashscope-default",
            "name": "阿里云百炼 · 对话与分析",
            "protocol": "openai_chat",
            "base_url": os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "model": "qwen-plus",
            "api_key": os.getenv("DASHSCOPE_API_KEY"),
            "capabilities": {
                "stream": True,
                "vision": False,
                "json": True,
                "embedding": False,
                "context_tokens": 32768,
            },
            "parameters": {},
            "enabled": True,
        },
        {
            "id": "dashscope-embedding",
            "name": "阿里云百炼 · 语义向量",
            "protocol": "openai_chat",
            "base_url": os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "model": "text-embedding-v4",
            "api_key": os.getenv("DASHSCOPE_API_KEY"),
            "capabilities": {
                "stream": False,
                "vision": False,
                "json": False,
                "embedding": True,
                "context_tokens": 8192,
            },
            "parameters": {"embedding_batch_size": 10},
            "enabled": True,
        },
    ]
    for template in templates:
        template["managed_template"] = True
        template["credential_source"] = "environment" if template["api_key"] else "missing"
        existing = store.profile(template["id"])
        if existing is None:
            # A deliberately deleted template must not reappear on restart.
            if not store.profile_versions(template["id"]):
                store.save_profile(template)
        elif existing.get("managed_template") and not existing["configured"] and template["api_key"]:
            store.save_profile(
                {
                    "api_key": template["api_key"],
                    "credential_source": "environment",
                    "configuration_notice": "已从本地环境载入密钥并创建新配置版本；请运行连接测试。",
                },
                profile_id=template["id"],
            )
            logger.info("Loaded environment credential into unconfigured managed model template")


def check_schema(schema):
    if schema is None:
        return

    def check_refs(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (
                    not isinstance(child, str) or not child.startswith("#")
                ):
                    raise ValueError("输出结构只允许本地 JSON Schema 引用，不加载外部地址")
                check_refs(child)
        elif isinstance(value, list):
            for child in value:
                check_refs(child)

    check_refs(schema)
    validator_for(schema).check_schema(schema)


def decode_structured(text, schema):
    candidate = text.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        lines = candidate.splitlines()
        if lines[0].strip().lower() in {"```", "```json"}:
            candidate = "\n".join(lines[1:-1])
    try:
        value = json.loads(candidate)
    except ValueError:
        raise ProviderError("invalid_json", "模型输出不是有效 JSON；已保留生成状态，请检查或重试") from None
    try:
        validator_for(schema)(schema, format_checker=FormatChecker()).validate(value)
    except ValidationError as exc:
        # Schema paths describe caller-owned rules, never echo model text, excerpts or secret values.
        rule_path = "/".join(str(part) for part in exc.absolute_schema_path)
        missing = [key for key in exc.validator_value if key not in exc.instance] if exc.validator == "required" and isinstance(exc.instance, dict) else []
        suffix = "；缺少字段：" + ",".join(missing) if missing else ""
        raise ProviderError(
            "schema_validation_failed", f"模型输出未满足请求指定的字段和结构要求（规则位置：{rule_path}{suffix}），未交付为成功"
        ) from None
    return value


class Runtime:
    def __init__(self, store, client, concurrency=1):
        self.store = store
        self.adapters = Adapters(client)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.tasks = {}
        self.shutting_down = False

    def schedule(self, request_id):
        task = asyncio.create_task(self.run(request_id), name=f"ai-request:{request_id}")
        self.tasks[request_id] = task
        task.add_done_callback(lambda completed: self.tasks.pop(request_id, None))

    async def run(self, request_id):
        try:
            async with self.semaphore:
                payload = self.store.payload(request_id)
                if not payload or not self.store.transition(request_id, "running"):
                    return
                profile = self.store.profile(payload["profile_id"], payload["profile_version"], private=True)
                if not profile or not profile["configured"]:
                    raise ProviderError("configuration_missing", "模型配置或凭据已失效，请修复后重新确认任务")

                async def emit(text):
                    self.store.emit(request_id, "text_delta", {"text": text})

                output = await self.adapters.execute(profile, payload, emit)
                result = {"model": output.model}
                if payload["operation"] == "embed":
                    result["vectors"] = output.vectors
                else:
                    result["text"] = output.text
                    if payload.get("output_schema") is not None:
                        result["json"] = decode_structured(output.text, payload["output_schema"])
                self.store.transition(
                    request_id,
                    "completed",
                    result=result,
                    usage=output.usage,
                    finish_reason=output.finish_reason,
                )
        except asyncio.CancelledError:
            status = "interrupted" if self.shutting_down else "cancelled"
            self.store.transition(
                request_id,
                status,
                error={
                    "code": status,
                    "message": "AI 服务已中断，待用户确认恢复"
                    if self.shutting_down
                    else "请求已取消，未自动继续生成",
                    "retryable": False,
                },
            )
        except ProviderError as exc:
            self.store.transition(
                request_id, "failed", error=exc.public(), usage=exc.usage, finish_reason=exc.finish_reason
            )
        except Exception:  # noqa: BLE001 -- persist a safe terminal state without exposing provider input
            # Do not log exception text or stack locals from SDKs: they may contain input or secrets.
            logger.error("AI request processing failed with an internal error")
            self.store.transition(
                request_id,
                "failed",
                error={
                    "code": "processing_failed",
                    "message": "AI 请求处理失败，已保留任务状态；请检查配置后重试",
                    "retryable": False,
                },
            )

    async def cancel(self, request_id):
        self.store.transition(
            request_id, "cancelled", error={"code": "cancelled", "message": "请求已取消", "retryable": False}
        )
        task = self.tasks.get(request_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def stop(self):
        self.shutting_down = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.store.interrupt_pending()


def create_app(data_dir=None, service_token=None, transport=None, seed=True):
    """Dependency arguments allow tests to use a temporary database and HTTP mock transport."""

    @asynccontextmanager
    async def lifespan(application):
        directory = Path(data_dir or os.getenv("MINDCHIME_DATA_DIR", ".data")) / "ai"
        with single_instance(directory):
            store = Store(directory)
            store.interrupt_pending()
            if seed:
                default_profiles(store)
            token = service_token if service_token is not None else os.getenv("MINDCHIME_AI_TOKEN", "")
            # Missing configuration never exposes an open API.
            application.state.token = token
            application.state.store = store
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(180, connect=20),
                transport=transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                runtime = Runtime(
                    store, client, concurrency=max(1, min(8, int(os.getenv("MINDCHIME_AI_CONCURRENCY", "1"))))
                )
                application.state.runtime = runtime
                try:
                    yield
                finally:
                    await runtime.stop()

    application = FastAPI(
        title="MindChime independent AI service",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default validation error includes input values (including api_key).
        fields = sorted(
            {".".join(str(part) for part in error["loc"] if part != "body") for error in exc.errors()}
        )
        return JSONResponse(status_code=422, content={"detail": "请求字段格式无效：" + ", ".join(fields)})

    @application.exception_handler(ConflictError)
    async def conflict_error(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    async def authorize(request: Request, x_service_token: str | None = Header(default=None)):
        expected = request.app.state.token
        if not expected:
            raise HTTPException(503, "AI 服务尚未设置 MINDCHIME_AI_TOKEN，请通过项目启动入口运行")
        if not x_service_token or not hmac.compare_digest(expected.encode(), x_service_token.encode()):
            raise HTTPException(401, "AI 服务身份验证失败")

    def store(request):
        return request.app.state.store

    def get_profile(request, profile_id):
        profile = store(request).profile(profile_id)
        if not profile:
            raise HTTPException(404, "模型配置不存在或已删除")
        return profile

    def get_request(request, request_id):
        result = store(request).find_request(request_id)
        if not result:
            raise HTTPException(404, "AI 请求不存在")
        return result

    def validate_config(data):
        try:
            validate_profile(data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @application.get("/health")
    async def health(request: Request):
        return {"status": "ok", "service": "ai", "configured": bool(request.app.state.token)}

    dependencies = [Depends(authorize)]

    @application.get("/ai/v1/profiles", dependencies=dependencies)
    async def list_profiles(request: Request):
        return store(request).profiles()

    @application.post("/ai/v1/profiles", dependencies=dependencies, status_code=201)
    async def create_profile(body: ProfileCreate, request: Request):
        data = body.model_dump(by_alias=True)
        validate_config(data)
        if data["id"] and store(request).profile_versions(data["id"]):
            raise HTTPException(409, "模型配置编号已存在，请使用新编号")
        data["credential_source"] = "user" if data.get("api_key") else "missing"
        return store(request).save_profile(data)

    @application.get("/ai/v1/profiles/{profile_id}", dependencies=dependencies)
    async def read_profile(profile_id: str, request: Request):
        return get_profile(request, profile_id)

    @application.get("/ai/v1/profiles/{profile_id}/versions", dependencies=dependencies)
    async def profile_versions(profile_id: str, request: Request):
        get_profile(request, profile_id)
        return store(request).profile_versions(profile_id)

    @application.patch("/ai/v1/profiles/{profile_id}", dependencies=dependencies)
    async def update_profile(profile_id: str, body: ProfilePatch, request: Request):
        existing = get_profile(request, profile_id)
        patch = body.model_dump(exclude_unset=True, by_alias=True)
        expected_version = patch.pop("expected_version", None)
        if any(value is None for key, value in patch.items() if key != "api_key"):
            raise HTTPException(422, "除清除密钥外，配置字段不能设置为 null")
        validate_config({**existing, **patch})
        patch["managed_template"] = False
        if "api_key" in patch:
            patch["credential_source"] = "user" if patch["api_key"] else "missing"
        return store(request).save_profile(patch, profile_id=profile_id, expected_version=expected_version)

    @application.delete("/ai/v1/profiles/{profile_id}", dependencies=dependencies)
    async def remove_profile(profile_id: str, request: Request):
        get_profile(request, profile_id)
        store(request).delete_profile(profile_id)
        return {"id": profile_id, "deleted": True}

    def validate_input(body, profile):
        if not profile.get("enabled"):
            raise HTTPException(400, "模型配置已停用，请启用或选择其他配置")
        if not profile.get("configured"):
            raise HTTPException(400, "模型未配置密钥，请在模型设置中填写并测试连接")
        try:
            check_schema(body.get("output_schema"))
            if body["operation"] == "generate":
                checked_messages(body, profile)
            elif not profile["capabilities"].get("embedding") or profile["protocol"] == "anthropic":
                raise ValueError("此配置不支持向量接口，请选择 embedding 模型")
        except ProviderError as exc:
            raise HTTPException(422, exc.message) from None
        except (ValueError, SchemaError):
            raise HTTPException(422, "输出结构或模型能力配置无效；仅支持本地 JSON Schema 引用") from None
        if body.get("max_tokens") and body["max_tokens"] > profile["capabilities"]["context_tokens"]:
            raise HTTPException(422, "输出上限超过此配置声明的上下文容量")
        if len(json.dumps(body, ensure_ascii=False)) > 8_000_000:
            raise HTTPException(413, "单次 AI 请求过大，请拆分为更小的处理范围")

    @application.post("/ai/v1/profiles/{profile_id}/test", dependencies=dependencies)
    async def test_profile(profile_id: str, request: Request):
        profile = get_profile(request, profile_id)
        payload = {
            "operation": "embed" if profile["capabilities"].get("embedding") else "generate",
            "prompt": "请只回答 OK。",
            "texts": ["连接测试"],
            "max_tokens": 128,
            "timeout_seconds": 45,
        }
        validate_input(payload, profile)
        private = store(request).profile(profile_id, private=True)

        async def no_emit(text):
            return None

        try:
            output = await request.app.state.runtime.adapters.execute(private, payload, no_emit)
        except ProviderError as exc:
            store(request).record_test(profile_id, profile["version"], False, exc.code)
            return JSONResponse(
                status_code=502, content={"detail": exc.message, "ok": False, "error": exc.public()}
            )
        store(request).record_test(profile_id, profile["version"], True)
        return {
            "ok": True,
            "profile_id": profile_id,
            "profile_version": profile["version"],
            "model": output.model,
            "operation": payload["operation"],
            "usage": output.usage,
            "message": "连接测试成功；这不代表实际资料的分析质量已经通过验证",
        }

    @application.post("/ai/v1/requests", dependencies=dependencies, status_code=202)
    async def submit(body: AIRequest, request: Request):
        payload = body.model_dump()
        fingerprint = Store.fingerprint(payload)
        existing = store(request).find_request(body.request_id, fingerprint)
        if existing:
            return existing
        current = get_profile(request, body.profile_id)
        if not current["enabled"]:
            raise HTTPException(400, "模型配置已停用")
        profile = (
            store(request).profile(body.profile_id, body.profile_version) if body.profile_version else current
        )
        if not profile:
            raise HTTPException(404, "请求指定的模型配置版本不存在")
        validate_input(payload, profile)
        result, created = store(request).create_request(payload, profile["version"], fingerprint)
        if created:
            request.app.state.runtime.schedule(body.request_id)
        return result

    @application.get("/ai/v1/requests/{request_id}", dependencies=dependencies)
    async def read_request(request_id: str, request: Request):
        return get_request(request, request_id)

    @application.get("/ai/v1/requests/{request_id}/events", dependencies=dependencies)
    async def events(
        request_id: str, request: Request, after: int = 0, last_event_id: str | None = Header(default=None)
    ):
        get_request(request, request_id)
        try:
            cursor = max(0, after, int(last_event_id or 0))
        except ValueError:
            raise HTTPException(422, "事件游标格式无效") from None

        async def stream():
            nonlocal cursor
            idle = 0
            while not await request.is_disconnected():
                batch = store(request).events(request_id, cursor)
                for event in batch:
                    cursor = event["id"]
                    yield f"id: {cursor}\nevent: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                state = store(request).find_request(request_id)
                if not state or (state["status"] in TERMINAL and len(batch) < 500):
                    return
                idle += 1
                if idle % 60 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @application.post("/ai/v1/requests/{request_id}/cancel", dependencies=dependencies)
    async def cancel(request_id: str, request: Request):
        get_request(request, request_id)
        await request.app.state.runtime.cancel(request_id)
        return get_request(request, request_id)

    @application.post("/ai/v1/requests/{request_id}/ack", dependencies=dependencies)
    async def acknowledge(request_id: str, request: Request):
        get_request(request, request_id)
        store(request).acknowledge(request_id)
        return get_request(request, request_id)

    @application.delete("/ai/v1/requests/{request_id}", dependencies=dependencies)
    async def delete_request(request_id: str, request: Request):
        get_request(request, request_id)
        await request.app.state.runtime.cancel(request_id)
        store(request).acknowledge(request_id)
        return {"id": request_id, "status": "acknowledged", "purged": True}

    from .research import install as install_research
    install_research(application, dependencies)
    return application


app = create_app()
