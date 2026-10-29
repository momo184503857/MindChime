"""Protocol adapters. They receive explicit context and cannot access business storage."""

import asyncio
import base64
import json
import math
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx


class ProviderError(Exception):
    def __init__(self, code, message, *, retryable=False, status=None, usage=None, finish_reason=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status = status
        self.usage = usage
        self.finish_reason = finish_reason

    def public(self):
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "provider_status": self.status,
        }


@dataclass
class Output:
    text: str = ""
    vectors: list = field(default_factory=list)
    model: str = ""
    usage: dict = field(default_factory=dict)
    finish_reason: str | None = None


RESERVED_PARAMETERS = {
    "api_key",
    "authorization",
    "headers",
    "extra_headers",
    "base_url",
    "model",
    "messages",
    "input",
    "prompt",
    "stream",
    "tools",
    "tool_choice",
    "store",
    "previous_response_id",
    "conversation",
    "web_search",
    "max_output_tokens",
    "max_completion_tokens",
    "response_format",
    "text",
    "system",
    "format",
    "n",
}
ALLOWED_PARAMETERS = {
    "max_tokens",
    "temperature",
    "top_p",
    "top_k",
    "frequency_penalty",
    "presence_penalty",
    "seed",
    "stop",
    "thinking",
    "reasoning_effort",
    "reasoning",
    "dimensions",
    "encoding_format",
    "options",
    "think",
    "keep_alive",
    "anthropic_version",
    "structured_output_mode",
    "embedding_batch_size",
    "include_usage",
    "chat_token_parameter",
}


def validate_profile(profile):
    url = urlsplit(profile["base_url"])
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
        raise ValueError("模型地址必须是有效的 HTTP(S) 地址，不能包含用户名或密码")
    if url.query or url.fragment:
        raise ValueError("模型地址不能包含查询参数或片段；密钥请填入专用字段")
    parameters = profile.get("parameters", {})
    if set(parameters) & RESERVED_PARAMETERS:
        raise ValueError("模型高级参数不能覆盖输入、密钥、地址、工具、状态存储或调用约束")
    if set(parameters) - ALLOWED_PARAMETERS:
        raise ValueError("包含当前适配器未支持的高级参数，请使用明确支持的参数")
    if parameters.get("structured_output_mode", "json_object") not in {
        "json_object",
        "json_schema",
        "prompt",
    }:
        raise ValueError("structured_output_mode 必须是 json_object、json_schema 或 prompt")
    batch_size = parameters.get("embedding_batch_size", 10)
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= 128:
        raise ValueError("embedding_batch_size 必须介于 1 与 128")
    if parameters.get("chat_token_parameter", "max_tokens") not in {"max_tokens", "max_completion_tokens"}:
        raise ValueError("聊天输出上限参数只能使用 max_tokens 或 max_completion_tokens")
    if "include_usage" in parameters and not isinstance(parameters["include_usage"], bool):
        raise ValueError("include_usage 必须为布尔值")
    if "options" in parameters and not isinstance(parameters["options"], dict):
        raise ValueError("Ollama options 必须为对象")
    if "max_tokens" in parameters:
        limit = parameters["max_tokens"]
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200000:
            raise ValueError("默认输出上限必须是 1–200000 的整数")
        if limit > profile.get("capabilities", {}).get("context_tokens", 32768):
            raise ValueError("默认输出上限不能超过配置的上下文容量")
    for field_name in ("name", "model"):
        if not str(profile.get(field_name, "")).strip():
            raise ValueError("模型名称和型号不能为空")


def endpoint(base, suffix):
    base = base.rstrip("/")
    if base.endswith(suffix):
        return base
    # Users may enter the native Ollama root or its /api prefix.
    if suffix.startswith("/api/") and base.endswith("/api"):
        return base + suffix[4:]
    if suffix == "/messages" and not base.endswith("/v1"):
        return base + "/v1/messages"
    if urlsplit(base).hostname == "api.openai.com" and not urlsplit(base).path:
        return base + "/v1" + suffix
    return base + suffix


def output_limit(profile, request):
    return request.get("max_tokens") or profile.get("parameters", {}).get("max_tokens") or 4096


def messages_for(request):
    messages = [dict(message) for message in (request.get("messages") or [])]
    if request.get("prompt"):
        messages.insert(0, {"role": "system", "content": request["prompt"]})
    if not messages:
        raise ProviderError("invalid_input", "未提供模型输入")
    if any(message["role"] == "tool" for message in messages):
        raise ProviderError("unsupported_input", "本版本不接受缺少调用关联的 tool 消息；请提供显式文本上下文")
    if all(message["role"] in {"system", "developer"} for message in messages):
        messages.append({"role": "user", "content": "请完成上述分析任务。"})
    return messages


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "output_text", "input_text"}
        )
    return ""


def has_images(messages):
    return any(
        isinstance(message["content"], list)
        and any(part.get("type") in {"image_url", "input_image", "image"} for part in message["content"])
        for message in messages
    )


def checked_messages(request, profile):
    messages = messages_for(request)
    if has_images(messages) and not profile["capabilities"].get("vision"):
        raise ProviderError("unsupported_capability", "此模型配置未启用图像输入能力，请选择支持图像的模型")
    valid_types = {"text", "input_text", "image_url", "input_image", "image"}
    for message in messages:
        if isinstance(message["content"], list):
            for part in message["content"]:
                if part.get("type") not in valid_types:
                    raise ProviderError("unsupported_input", "包含不支持的消息内容类型")
    return messages


def schema_instruction(messages, schema):
    if schema:
        # This is a caller-specified output constraint, not additional business instructions.
        instruction = "Return only a JSON value matching this caller-provided JSON Schema:\n" + json.dumps(
            schema, ensure_ascii=False
        )
        messages = [{"role": "system", "content": instruction}, *messages]
    return messages


def image_url(part):
    image = part.get("image_url", part.get("url", ""))
    return image.get("url", "") if isinstance(image, dict) else image


def anthropic_content(content):
    if isinstance(content, str):
        return content
    result = []
    for part in content:
        if part["type"] in {"text", "input_text"}:
            result.append({"type": "text", "text": part.get("text", "")})
        elif part["type"] == "image" and isinstance(part.get("source"), dict):
            result.append(part)
        else:
            url = image_url(part)
            if url.startswith("data:"):
                try:
                    prefix, data = url.split(",", 1)
                    media_type = prefix[5:].split(";")[0]
                    if ";base64" not in prefix or not media_type.startswith("image/"):
                        raise ValueError()
                    base64.b64decode(data, validate=True)
                except (ValueError, TypeError):
                    raise ProviderError("invalid_image", "图片 data URL 格式无效") from None
                result.append(
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
                )
            elif url.startswith(("https://", "http://")):
                result.append({"type": "image", "source": {"type": "url", "url": url}})
            else:
                raise ProviderError("invalid_image", "图片必须使用显式 URL 或 base64 内容")
    return result


async def sse_frames(response):
    event, lines = "", []
    async for line in response.aiter_lines():
        if not line:
            if lines:
                yield event, "\n".join(lines)
            event, lines = "", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            lines.append(line[5:].lstrip())
    if lines:
        yield event, "\n".join(lines)


def parse_json(value):
    try:
        result = json.loads(value)
        if not isinstance(result, dict):
            raise TypeError()
        return result
    except (ValueError, TypeError):
        raise ProviderError(
            "invalid_provider_response", "模型服务返回了无法解析的数据；本次未标记为成功"
        ) from None


def http_error(status):
    if status in {401, 403}:
        return ProviderError(
            "authentication_failed", "模型身份验证失败，请检查密钥及模型访问权限", status=status
        )
    if status == 402:
        return ProviderError("quota_exhausted", "模型服务余额或配额不足，请到服务商检查账户", status=status)
    if status == 429:
        return ProviderError(
            "rate_limited", "模型服务限流或配额不足，请稍后重试并检查账户额度", status=status, retryable=True
        )
    if status == 404:
        return ProviderError(
            "model_or_endpoint_missing", "模型或接口不存在，请检查模型名称、协议及服务地址", status=status
        )
    if status in {400, 413, 422}:
        return ProviderError(
            "provider_rejected", "模型服务拒绝输入，请检查上下文长度、能力和高级参数", status=status
        )
    return ProviderError(
        "provider_unavailable", "模型服务暂时不可用；未自动重复可能已接受的请求", status=status
    )


async def checked_response(response):
    if response.status_code >= 400:
        # Never reflect provider bodies: they can include prompts, credentials, or private endpoint details.
        raise http_error(response.status_code)


def check_finished(output):
    if output.finish_reason in {"length", "max_tokens", "max_output_tokens", "incomplete"}:
        raise ProviderError(
            "output_truncated",
            "模型输出达到长度上限，结果不完整；请减少输入或调整输出上限",
            usage=output.usage,
            finish_reason=output.finish_reason,
        )
    if output.finish_reason in {"content_filter", "refusal", "safety", "blocked"}:
        raise ProviderError(
            "provider_refusal",
            "模型服务未提供本次内容，请调整请求或选择其他模型",
            usage=output.usage,
            finish_reason=output.finish_reason,
        )
    if output.finish_reason in {"tool_calls", "function_call", "tool_use"}:
        raise ProviderError(
            "unexpected_tool_call",
            "模型返回了当前任务未授权的工具调用，未执行任何外部操作",
            usage=output.usage,
        )
    if not output.text.strip():
        raise ProviderError("empty_output", "模型未返回可用正文，本次未标记为成功", usage=output.usage)
    return output


class Adapters:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def execute(self, profile, request, emit):
        try:
            async with asyncio.timeout(request.get("timeout_seconds", 180)):
                if request["operation"] == "embed":
                    return await self.embed(profile, request)
                return await getattr(self, profile["protocol"])(profile, request, emit)
        except TimeoutError:
            raise ProviderError(
                "timeout", "模型请求超时，服务商可能已处理部分内容；不会自动重发，请确认后重试"
            ) from None
        except httpx.TimeoutException:
            raise ProviderError("timeout", "模型连接或响应超时；不会自动重发可能已接受的请求") from None
        except httpx.ConnectError:
            raise ProviderError(
                "connection_failed", "无法连接模型服务，请检查地址、网络和本地服务运行状态", retryable=True
            ) from None
        except httpx.HTTPError:
            raise ProviderError(
                "connection_interrupted", "模型连接中断，未将部分输出当作完整结果，也未自动重新调用"
            ) from None
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            raise ProviderError(
                "invalid_provider_response", "模型服务返回的字段结构不正确，本次未标记为成功"
            ) from None

    @staticmethod
    def headers(profile):
        headers = {"Content-Type": "application/json"}
        if profile.get("api_key"):
            if profile["protocol"] == "anthropic":
                headers["x-api-key"] = profile["api_key"]
            else:
                headers["Authorization"] = "Bearer " + profile["api_key"]
        if profile["protocol"] == "anthropic":
            headers["anthropic-version"] = profile.get("parameters", {}).get(
                "anthropic_version", "2023-06-01"
            )
        return headers

    @staticmethod
    def parameters(profile, allowed):
        return {key: value for key, value in profile.get("parameters", {}).items() if key in allowed}

    async def openai_chat(self, profile, request, emit):
        schema = request.get("output_schema")
        messages = schema_instruction(checked_messages(request, profile), schema)
        body = {
            "model": profile["model"],
            "messages": messages,
            "stream": profile["capabilities"].get("stream", True),
        }
        token_parameter = profile.get("parameters", {}).get("chat_token_parameter", "max_tokens")
        body[token_parameter] = output_limit(profile, request)
        if body["stream"] and profile.get("parameters", {}).get("include_usage", True):
            body["stream_options"] = {"include_usage": True}
        body.update(
            self.parameters(
                profile,
                {
                    "temperature",
                    "top_p",
                    "frequency_penalty",
                    "presence_penalty",
                    "seed",
                    "stop",
                    "thinking",
                    "reasoning_effort",
                },
            )
        )
        mode = profile.get("parameters", {}).get("structured_output_mode", "json_object")
        if schema and profile["capabilities"].get("json") and mode != "prompt":
            body["response_format"] = (
                {
                    "type": "json_schema",
                    "json_schema": {"name": "analysis_result", "strict": True, "schema": schema},
                }
                if mode == "json_schema"
                else {"type": "json_object"}
            )
        output = Output(model=profile["model"])
        async with self.client.stream(
            "POST",
            endpoint(profile["base_url"], "/chat/completions"),
            headers=self.headers(profile),
            json=body,
        ) as response:
            await checked_response(response)
            if not body["stream"]:
                data = parse_json(await response.aread())
                choices = data.get("choices") or []
                if not choices:
                    raise ProviderError("invalid_provider_response", "模型响应缺少结果")
                output.text = text_content(choices[0].get("message", {}).get("content"))
                output.finish_reason = choices[0].get("finish_reason")
                output.usage = data.get("usage") or {}
                output.model = data.get("model") or output.model
            else:
                ended = False
                async for _, frame in sse_frames(response):
                    if frame == "[DONE]":
                        ended = True
                        break
                    data = parse_json(frame)
                    if data.get("error"):
                        raise ProviderError(
                            "provider_stream_error", "模型服务在生成途中报告错误，已保留输出进度"
                        )
                    if data.get("usage"):
                        output.usage = data["usage"]
                    output.model = data.get("model") or output.model
                    for choice in data.get("choices") or []:
                        if choice.get("index", 0) != 0:
                            continue
                        delta = text_content(choice.get("delta", {}).get("content"))
                        if delta:
                            output.text += delta
                            await emit(delta)
                        if choice.get("finish_reason"):
                            output.finish_reason = choice["finish_reason"]
                            ended = True
                if not ended:
                    raise ProviderError("incomplete_stream", "模型流连接在完成标记前结束，结果未交付为成功")
        if not body["stream"] and output.text:
            await emit(output.text)
        return check_finished(output)

    async def openai_responses(self, profile, request, emit):
        messages = schema_instruction(checked_messages(request, profile), request.get("output_schema"))
        items = []
        for message in messages:
            content = message["content"]
            if isinstance(content, list):
                transformed = []
                for part in content:
                    if part["type"] in {"text", "input_text"}:
                        transformed.append(
                            {
                                "type": "output_text" if message["role"] == "assistant" else "input_text",
                                "text": part.get("text", ""),
                            }
                        )
                    else:
                        transformed.append({"type": "input_image", "image_url": image_url(part)})
                content = transformed
            items.append({"role": message["role"], "content": content})
        body = {
            "model": profile["model"],
            "input": items,
            "store": False,
            "max_output_tokens": output_limit(profile, request),
            "stream": profile["capabilities"].get("stream", True),
        }
        body.update(self.parameters(profile, {"temperature", "top_p", "reasoning"}))
        if "reasoning_effort" in profile.get("parameters", {}):
            body.setdefault("reasoning", {"effort": profile["parameters"]["reasoning_effort"]})
        schema = request.get("output_schema")
        mode = profile.get("parameters", {}).get("structured_output_mode", "json_object")
        if schema and profile["capabilities"].get("json") and mode != "prompt":
            body["text"] = {
                "format": {"type": "json_schema", "name": "analysis_result", "schema": schema, "strict": True}
                if mode == "json_schema"
                else {"type": "json_object"}
            }
        output = Output(model=profile["model"])
        async with self.client.stream(
            "POST", endpoint(profile["base_url"], "/responses"), headers=self.headers(profile), json=body
        ) as response:
            await checked_response(response)
            if not body["stream"]:
                data = parse_json(await response.aread())
                self.responses_result(data, output)
            else:
                ended = False
                async for event, frame in sse_frames(response):
                    if frame == "[DONE]":
                        continue
                    data = parse_json(frame)
                    kind = data.get("type", event)
                    if kind == "response.output_text.delta":
                        delta = data.get("delta", "")
                        output.text += delta
                        await emit(delta)
                    elif kind in {"response.completed", "response.incomplete", "response.failed"}:
                        self.responses_result(data.get("response", {}), output)
                        ended = True
                    elif kind == "error":
                        raise ProviderError("provider_stream_error", "模型服务在生成中报告错误")
                if not ended:
                    raise ProviderError("incomplete_stream", "模型流未收到最终完成状态")
        if not body["stream"] and output.text:
            await emit(output.text)
        return check_finished(output)

    @staticmethod
    def responses_result(data, output):
        output.usage = data.get("usage") or output.usage
        output.model = data.get("model") or output.model
        status = data.get("status")
        if status == "failed" or data.get("error"):
            raise ProviderError("provider_error", "模型服务未完成分析请求", usage=output.usage)
        output.finish_reason = "incomplete" if status == "incomplete" else "stop"
        text = "".join(
            text_content(item.get("content", []))
            for item in data.get("output", [])
            if item.get("type") == "message"
        )
        if any(
            item.get("type") in {"function_call", "custom_tool_call", "web_search_call"}
            for item in data.get("output", [])
        ):
            output.finish_reason = "tool_calls"
        if text:
            output.text = text

    async def anthropic(self, profile, request, emit):
        messages = schema_instruction(checked_messages(request, profile), request.get("output_schema"))
        systems, items = [], []
        for message in messages:
            if message["role"] in {"system", "developer"}:
                systems.append(text_content(message["content"]))
            else:
                items.append({"role": message["role"], "content": anthropic_content(message["content"])})
        if not items:
            items = [{"role": "user", "content": "请完成上述分析任务。"}]
        body = {
            "model": profile["model"],
            "system": "\n\n".join(systems),
            "messages": items,
            "max_tokens": output_limit(profile, request),
            "stream": profile["capabilities"].get("stream", True),
        }
        body.update(self.parameters(profile, {"temperature", "top_p", "top_k", "thinking"}))
        output = Output(model=profile["model"])
        async with self.client.stream(
            "POST", endpoint(profile["base_url"], "/messages"), headers=self.headers(profile), json=body
        ) as response:
            await checked_response(response)
            if not body["stream"]:
                data = parse_json(await response.aread())
                output.text = text_content(data.get("content"))
                output.usage = data.get("usage") or {}
                output.finish_reason = data.get("stop_reason")
                output.model = data.get("model") or output.model
            else:
                ended = False
                async for event, frame in sse_frames(response):
                    data = parse_json(frame)
                    kind = data.get("type", event)
                    if kind == "message_start":
                        message = data.get("message", {})
                        output.usage.update(message.get("usage") or {})
                        output.model = message.get("model") or output.model
                    elif kind == "content_block_delta" and data.get("delta", {}).get("type") == "text_delta":
                        delta = data["delta"].get("text", "")
                        output.text += delta
                        await emit(delta)
                    elif kind == "message_delta":
                        output.finish_reason = (
                            data.get("delta", {}).get("stop_reason") or output.finish_reason
                        )
                        output.usage.update(data.get("usage") or {})
                    elif kind == "message_stop":
                        ended = True
                    elif kind == "error":
                        raise ProviderError("provider_stream_error", "模型服务在生成过程中报告错误")
                if not ended:
                    raise ProviderError("incomplete_stream", "模型流在完整消息结束前断开")
        if not body["stream"] and output.text:
            await emit(output.text)
        return check_finished(output)

    async def ollama(self, profile, request, emit):
        messages = schema_instruction(checked_messages(request, profile), request.get("output_schema"))
        items = []
        for message in messages:
            item = {
                "role": "system" if message["role"] == "developer" else message["role"],
                "content": text_content(message["content"]),
            }
            if isinstance(message["content"], list):
                images = []
                for part in message["content"]:
                    if part["type"] not in {"text", "input_text"}:
                        url = image_url(part)
                        if not url.startswith("data:image/") or ";base64," not in url:
                            raise ProviderError(
                                "unsupported_image", "Ollama 图片输入须使用 base64 data URL，不读取本地路径"
                            )
                        images.append(url.split(",", 1)[1])
                if images:
                    item["images"] = images
            items.append(item)
        options = dict(profile.get("parameters", {}).get("options", {}))
        options.update(self.parameters(profile, {"temperature", "top_p", "top_k", "seed", "stop"}))
        options["num_predict"] = output_limit(profile, request)
        body = {
            "model": profile["model"],
            "messages": items,
            "options": options,
            "stream": profile["capabilities"].get("stream", True),
        }
        body.update(self.parameters(profile, {"think", "keep_alive"}))
        if request.get("output_schema") and profile["capabilities"].get("json"):
            body["format"] = request["output_schema"]
        output = Output(model=profile["model"])
        async with self.client.stream(
            "POST", endpoint(profile["base_url"], "/api/chat"), headers=self.headers(profile), json=body
        ) as response:
            await checked_response(response)

            async def chunks():
                if not body["stream"]:
                    yield parse_json(await response.aread())
                else:
                    async for line in response.aiter_lines():
                        if line.strip():
                            yield parse_json(line)

            ended = False
            async for data in chunks():
                if data.get("error"):
                    raise ProviderError(
                        "provider_error", "Ollama 未完成请求，请检查模型是否已安装或内存是否充足"
                    )
                delta = data.get("message", {}).get("content", "")
                if data.get("message", {}).get("tool_calls"):
                    output.finish_reason = "tool_calls"
                output.text += delta
                output.model = data.get("model") or output.model
                if delta:
                    await emit(delta)
                if data.get("done"):
                    ended = True
                    output.finish_reason = output.finish_reason or data.get("done_reason", "stop")
                    output.usage = {
                        "input_tokens": data.get("prompt_eval_count"),
                        "output_tokens": data.get("eval_count"),
                    }
            if not ended:
                raise ProviderError("incomplete_stream", "Ollama 未返回完整结束标记")
        return check_finished(output)

    async def embed(self, profile, request):
        if not profile["capabilities"].get("embedding"):
            raise ProviderError("unsupported_capability", "当前配置不支持向量，请配置独立 embedding 模型")
        if profile["protocol"] == "anthropic":
            raise ProviderError("unsupported_capability", "Anthropic Messages 协议未提供本服务可用的向量接口")
        batch_size = profile.get("parameters", {}).get("embedding_batch_size", 10)
        combined = Output(model=profile["model"], finish_reason="stop")
        for start in range(0, len(request["texts"]), batch_size):
            result = await self.embed_batch(profile, request["texts"][start : start + batch_size])
            if combined.vectors and len(combined.vectors[0]) != len(result.vectors[0]):
                raise ProviderError("invalid_embeddings", "不同批次的向量维度不一致，未发布部分索引")
            combined.vectors.extend(result.vectors)
            combined.model = result.model
            for key, value in result.usage.items():
                if isinstance(value, (int, float)):
                    combined.usage[key] = combined.usage.get(key, 0) + value
            combined.usage["provider_calls"] = combined.usage.get("provider_calls", 0) + 1
        return combined

    async def embed_batch(self, profile, texts):
        body = {"model": profile["model"], "input": texts}
        if profile["protocol"] == "ollama":
            path = "/api/embed"
            body["truncate"] = False
        else:
            path = "/embeddings"
            body.update(self.parameters(profile, {"dimensions"}))
            body["encoding_format"] = "float"
        response = await self.client.post(
            endpoint(profile["base_url"], path), headers=self.headers(profile), json=body
        )
        await checked_response(response)
        data = parse_json(response.content)
        if profile["protocol"] == "ollama":
            vectors = data.get("embeddings", [])
            usage = {"input_tokens": data.get("prompt_eval_count")}
        else:
            indexed = data.get("data", [])
            if len(indexed) != len(texts) or sorted(item.get("index", -1) for item in indexed) != list(
                range(len(indexed))
            ):
                raise ProviderError("invalid_embeddings", "向量响应数量或顺序编号不正确")
            vectors = [item.get("embedding") for item in sorted(indexed, key=lambda item: item["index"])]
            usage = data.get("usage") or {}
        if len(vectors) != len(texts) or not vectors:
            raise ProviderError("invalid_embeddings", "向量响应数量与输入不一致")
        dimension = len(vectors[0]) if isinstance(vectors[0], list) else 0
        if not dimension or any(
            not isinstance(vector, list)
            or len(vector) != dimension
            or any(
                not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value)
                for value in vector
            )
            for vector in vectors
        ):
            raise ProviderError("invalid_embeddings", "模型返回了无效、维度不一致或非有限值向量")
        return Output(
            vectors=vectors, model=data.get("model", profile["model"]), usage=usage, finish_reason="stop"
        )
