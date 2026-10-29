from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Protocol = Literal["openai_chat", "openai_responses", "anthropic", "ollama"]


class Capabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stream: bool = True
    vision: bool = False
    json_output: bool = Field(default=True, alias="json")
    embedding: bool = False
    context_tokens: int = Field(default=32768, ge=256, le=10_000_000)


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    protocol: Protocol
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=8192, repr=False)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("name", "model", "base_url")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("内容不能只有空白")
        return value.strip()


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    protocol: Protocol | None = None
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=8192, repr=False)
    capabilities: Capabilities | None = None
    parameters: dict[str, Any] | None = None
    enabled: bool | None = None
    expected_version: int | None = Field(default=None, ge=1)


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]]


class AIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=160)
    operation: Literal["generate", "embed"] = "generate"
    profile_id: str = Field(min_length=1, max_length=128)
    profile_version: int | None = Field(default=None, ge=1)
    prompt: str | None = Field(default=None, max_length=4_000_000)
    messages: list[Message] | None = Field(default=None, max_length=1000)
    texts: list[str] | None = Field(default=None, min_length=1, max_length=128)
    output_schema: dict[str, Any] | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=200_000)
    timeout_seconds: float = Field(default=180, ge=1, le=3600)
    prompt_version: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def validate_operation(self):
        if not self.request_id.strip():
            raise ValueError("request_id 不能为空")
        if self.operation == "embed":
            if not self.texts or any(not text.strip() for text in self.texts):
                raise ValueError("向量请求需要非空文本列表")
            if sum(len(text) for text in self.texts) > 4_000_000:
                raise ValueError("向量请求文本总量过大，请分批处理")
            if self.prompt or self.messages or self.output_schema:
                raise ValueError("向量请求不能包含聊天提示词或输出结构")
        elif not ((self.prompt and self.prompt.strip()) or self.messages):
            raise ValueError("生成请求需要提示词或消息")
        return self
