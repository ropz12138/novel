"""old 与 new 完全相同时，只调整下一次 agent 模型请求的采样参数。"""
from __future__ import annotations

import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_FLAG = "identical_replacement_sampling"

_SAMPLING_BY_FAMILY = (
    ("deepseek", {"temperature": 2}),
    ("glm", {"top_p": 1}),
    ("mimo", {"temperature": 1.5}),
    ("qwen", {"temperature": 1.8}),
    ("gpt", {"temperature": 2}),
    ("gemini", {"temperature": 2}),
)


def sampling_override_for_model(model_name: str) -> dict:
    lowered = model_name.lower()
    for family, override in _SAMPLING_BY_FAMILY:
        if family in lowered:
            return dict(override)
    raise ValueError(f"模型 {model_name} 没有 old 与 new 相同时的采样参数")


def arm_identical_replacement_sampling() -> None:
    from services.agents.supervisor import _current_context

    context = _current_context.get()
    if context is None:
        return
    context[_FLAG] = True


def _consume_identical_replacement_sampling() -> bool:
    from services.agents.supervisor import _current_context

    context = _current_context.get()
    if not context or not context.get(_FLAG):
        return False
    context[_FLAG] = False
    return True


def _model_configs(llm) -> list:
    from services.thinking_llm import FallbackLLM

    if isinstance(llm, FallbackLLM):
        return _model_configs(llm._primary) + _model_configs(llm._fallback)
    provider = llm.provider
    configs = [provider.client.config]
    if provider.fallback_client is not None:
        configs.append(provider.fallback_client.config)
    return configs


@contextmanager
def supervisor_sampling_scope(llm):
    if not _consume_identical_replacement_sampling():
        yield
        return
    planned = []
    for config in _model_configs(llm):
        planned.append((config, dict(config.extra_body), sampling_override_for_model(config.name)))
    try:
        for config, snapshot, override in planned:
            config.extra_body.clear()
            config.extra_body.update(snapshot)
            config.extra_body.update(override)
            logger.info(
                "identical replacement sampling model=%s override=%s",
                config.name,
                override,
            )
        yield
    finally:
        for config, snapshot, _override in planned:
            config.extra_body.clear()
            config.extra_body.update(snapshot)
