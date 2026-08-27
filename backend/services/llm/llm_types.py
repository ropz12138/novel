from dataclasses import dataclass, field
from typing import Any, Literal

LLMProviderName = Literal["openai", "anthropic"]
LLMModelType = Literal["llm", "vlm"]


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
