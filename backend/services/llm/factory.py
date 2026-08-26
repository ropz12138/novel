"""从 Novel config.json 组装 LLMModelConfig。找不到指定模型时直接报错，不换别的模型。"""
from __future__ import annotations

from config import settings
from services.llm.llm_types import LLMModelConfig


def resolve_model_names(
    primary: str | None = None,
    fallback: str | None = None,
    *,
    model_name: str | None = None,
) -> tuple[str, str | None]:
    primary_name = primary or model_name or settings.default_model
    if not primary_name:
        raise ValueError("未配置 default_model，无法创建 LLM")
    fallback_name = fallback if fallback is not None else settings.fallback_model
    if fallback_name == "":
        fallback_name = None
    return primary_name, fallback_name


def build_model_config(model_name: str, *, temperature: float | None = None) -> LLMModelConfig:
    raw = settings.get_model_config(model_name)
    extra = dict(raw.get("extra_body") or {})
    if temperature is not None:
        extra["temperature"] = temperature
    provider = raw.get("provider") or "openai"
    if provider not in ("openai", "anthropic"):
        raise ValueError(f"不支持的 LLM provider: {provider}")
    model_type = raw.get("model_type") or "llm"
    if model_type not in ("llm", "vlm"):
        raise ValueError(f"不支持的 model_type: {model_type}")
    return LLMModelConfig(
        name=model_name,
        base_url=raw["base_url"],
        api_key=raw["api_key"],
        provider=provider,
        model=raw.get("model") or model_name,
        model_type=model_type,
        enable_thinking=raw.get("enable_thinking"),
        extra_body=extra,
    )
