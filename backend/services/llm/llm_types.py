from dataclasses import dataclass, field
from typing import Any, Literal

ChatRole = Literal["system", "user", "assistant"]
LLMProviderName = Literal["openai", "anthropic"]
LLMModelType = Literal["llm", "vlm"]
MessageContent = str | list[dict[str, Any]]


@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: MessageContent

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class LLMModelConfig:
    name: str
    base_url: str
    api_key: str
    provider: LLMProviderName
    model: str
    model_type: LLMModelType = "llm"
    enable_thinking: bool | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)
