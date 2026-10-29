"""Protocol contract verification using explicit HTTP response fixtures, not live model acceptance."""

import json

import httpx
import pytest
from ai_service.adapters import Adapters, ProviderError, endpoint


def stream(*items):
    return "".join(
        "data: " + (item if isinstance(item, str) else json.dumps(item)) + "\n\n" for item in items
    )


def profile(protocol="openai_chat", **extra):
    return {
        "protocol": protocol,
        "base_url": "https://provider.test/v1",
        "model": "contract-model",
        "api_key": "contract-test-key",
        "parameters": {},
        "capabilities": {"stream": True, "vision": True, "json": True, "embedding": True},
        **extra,
    }


async def execute(handler, config=None, payload=None):
    deltas = []

    async def emit(text):
        deltas.append(text)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await Adapters(client).execute(
            config or profile(),
            {"operation": "generate", "prompt": "context", "timeout_seconds": 3, **(payload or {})},
            emit,
        )
    return result, deltas


@pytest.mark.parametrize("usage_style", ["deepseek", "openai"])
async def test_chat_stream_preserves_usage_for_both_final_chunk_styles(usage_style):
    usage = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}
    events = [
        {
            "choices": [
                {"index": 0, "delta": {"reasoning_content": "private reasoning"}, "finish_reason": None}
            ]
        },
        {"choices": [{"index": 0, "delta": {"content": "真实"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {"content": "正文"}, "finish_reason": None}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    if usage_style == "deepseek":
        events[-1]["usage"] = usage
    else:
        events.append({"choices": [], "usage": usage})
    events.append("[DONE]")

    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        assert body["stream_options"] == {"include_usage": True}
        assert body["messages"][0] == {"role": "system", "content": "context"}
        assert "tools" not in body
        return httpx.Response(200, text=stream(*events), headers={"Content-Type": "text/event-stream"})

    result, deltas = await execute(handler)
    assert result.text == "真实正文" and deltas == ["真实", "正文"]
    assert result.usage == usage


async def test_responses_uses_items_and_typed_stream_events():
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert "messages" not in body and body["store"] is False
        assert body["text"]["format"]["schema"] == schema
        assert body["text"]["format"]["type"] == "json_schema"
        assert body["input"][-1]["content"][1] == {
            "type": "input_image",
            "image_url": "data:image/png;base64,AAAA",
        }
        return httpx.Response(
            200,
            text=stream(
                {"type": "response.created", "response": {"status": "in_progress"}},
                {"type": "response.output_text.delta", "delta": '{"ok":'},
                {"type": "response.output_text.delta", "delta": "true}"},
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "model": "responses-test",
                        "output": [
                            {"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]}
                        ],
                        "usage": {"input_tokens": 8, "output_tokens": 4},
                    },
                },
            ),
        )

    result, deltas = await execute(
        handler,
        profile("openai_responses", parameters={"structured_output_mode": "json_schema"}),
        {
            "output_schema": schema,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "read"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                    ],
                }
            ],
        },
    )
    assert result.text == '{"ok":true}' and len(deltas) == 2
    assert result.model == "responses-test" and result.usage["input_tokens"] == 8


async def test_anthropic_system_content_blocks_and_stream_stop():
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "contract-test-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert body["system"] == "context"
        assert body["messages"][0]["content"][1]["source"] == {
            "type": "base64",
            "media_type": "image/png",
            "data": "AAAA",
        }
        return httpx.Response(
            200,
            text=stream(
                {
                    "type": "message_start",
                    "message": {"model": "anthropic-test", "usage": {"input_tokens": 7}},
                },
                {
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "not content"},
                },
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "answer"}},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 3},
                },
                {"type": "message_stop"},
            ),
        )

    result, deltas = await execute(
        handler,
        profile("anthropic", base_url="https://api.anthropic.com"),
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "read"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                    ],
                }
            ]
        },
    )
    assert result.text == "answer" and deltas == ["answer"]
    assert result.usage == {"input_tokens": 7, "output_tokens": 3}


async def test_ollama_ndjson_stream_and_options():
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/api/chat"
        assert body["options"]["num_predict"] == 99
        assert body["messages"][-1]["images"] == ["AAAA"]
        return httpx.Response(
            200,
            text="\n".join(
                json.dumps(item)
                for item in [
                    {"message": {"content": "one"}, "done": False},
                    {
                        "message": {"content": "two"},
                        "done": True,
                        "done_reason": "stop",
                        "prompt_eval_count": 3,
                        "eval_count": 2,
                    },
                ]
            ),
        )

    result, deltas = await execute(
        handler,
        profile("ollama", base_url="http://localhost:11434/api"),
        {
            "max_tokens": 99,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "read"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                    ],
                }
            ],
        },
    )
    assert result.text == "onetwo" and deltas == ["one", "two"]
    assert result.usage == {"input_tokens": 3, "output_tokens": 2}


async def test_ollama_nonstream_pretty_json():
    def handler(request):
        assert json.loads(request.content)["stream"] is False
        return httpx.Response(
            200, text=json.dumps({"message": {"content": "answer"}, "done": True}, indent=2)
        )

    result, _ = await execute(handler, profile("ollama", capabilities={"stream": False}))
    assert result.text == "answer"


@pytest.mark.parametrize(
    "protocol,content",
    [
        ("openai_chat", stream({"choices": [{"delta": {"content": "partial"}}]})),
        ("openai_responses", stream({"type": "response.output_text.delta", "delta": "partial"})),
        (
            "anthropic",
            stream({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "partial"}}),
        ),
        ("ollama", '{"message":{"content":"partial"},"done":false}\n'),
    ],
)
async def test_truncated_connections_never_become_completed(protocol, content):
    with pytest.raises(ProviderError) as failure:
        await execute(lambda request: httpx.Response(200, text=content), profile(protocol))
    assert failure.value.code == "incomplete_stream"


@pytest.mark.parametrize(
    "finish_reason,code",
    [
        ("length", "output_truncated"),
        ("content_filter", "provider_refusal"),
        ("tool_calls", "unexpected_tool_call"),
    ],
)
async def test_chat_non_success_finish_reasons(finish_reason, code):
    content = stream(
        {"choices": [{"delta": {"content": "partial"}, "finish_reason": finish_reason}]}, "[DONE]"
    )
    with pytest.raises(ProviderError) as failure:
        await execute(lambda request: httpx.Response(200, text=content))
    assert failure.value.code == code


@pytest.mark.parametrize(
    "status,expected", [("incomplete", "output_truncated"), ("failed", "provider_error")]
)
async def test_responses_final_failure_is_not_success(status, expected):
    content = stream(
        {"type": "response.output_text.delta", "delta": "partial"},
        {"type": "response." + status, "response": {"status": status}},
    )
    with pytest.raises(ProviderError) as failure:
        await execute(lambda request: httpx.Response(200, text=content), profile("openai_responses"))
    assert failure.value.code == expected


async def test_ollama_embeddings_do_not_silently_truncate_input():
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/api/embed" and body["truncate"] is False
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]], "prompt_eval_count": 2})

    result, _ = await execute(
        handler,
        profile("ollama", base_url="http://localhost:11434"),
        {"operation": "embed", "texts": ["text"]},
    )
    assert result.vectors == [[1.0, 0.0]]


def test_endpoints_accept_standard_roots_and_prefixed_gateways():
    assert (
        endpoint("https://api.openai.com", "/chat/completions")
        == "https://api.openai.com/v1/chat/completions"
    )
    assert (
        endpoint("https://api.deepseek.com", "/chat/completions")
        == "https://api.deepseek.com/chat/completions"
    )
    assert (
        endpoint("https://api.deepseek.com/anthropic", "/messages")
        == "https://api.deepseek.com/anthropic/v1/messages"
    )
    assert endpoint("https://proxy.test/v1", "/messages") == "https://proxy.test/v1/messages"
    assert endpoint("http://localhost:11434/api/chat", "/api/chat") == "http://localhost:11434/api/chat"
