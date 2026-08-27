"""主备 LLM 包装：业务失败切备用模型。"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.runnables import Runnable, RunnableConfig

logger = logging.getLogger(__name__)


def has_meaningful_ai_output(value: Any) -> bool:
    """判断一次 AI 响应是否包含可供调用方继续处理的有效输出。

    OpenAI 兼容中转在业务失败时可能仍正常结束 HTTP/SSE，只返回一个空
    AIMessageChunk。正文、推理内容和工具调用全为空时，应视为模型调用失败，
    以便 FallbackLLM 切换备用模型。
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())

    content = getattr(value, "content", None)
    if isinstance(content, str) and content.strip():
        return True
    if isinstance(content, list):
        for part in content:
            if isinstance(part, str) and part.strip():
                return True
            if isinstance(part, Mapping):
                text = part.get("text") or part.get("content")
                if isinstance(text, str) and text.strip():
                    return True

    additional_kwargs = getattr(value, "additional_kwargs", None) or {}
    reasoning = additional_kwargs.get("reasoning_content")
    if reasoning is not None and str(reasoning).strip():
        return True
    if additional_kwargs.get("tool_calls"):
        return True

    return any(
        bool(getattr(value, attr, None))
        for attr in ("tool_calls", "tool_call_chunks", "invalid_tool_calls")
    )


class FallbackLLM(Runnable):
    """主模型任意业务报错都自动切换到备选模型重试。

    系统级异常（KeyboardInterrupt / GeneratorExit / asyncio.CancelledError 等
    ``BaseException``）不会被 ``except Exception`` 捕获，自然向上传播、不触发切换。
    流式方法在主模型已吐出部分内容后报错，也会从头重流备用模型（可能产生前缀重复，
    由调用方决定如何处理）。
    """

    def __init__(self, primary, fallback):
        self._primary = primary
        self._fallback = fallback

    def __getattr__(self, name: str):
        return getattr(self._primary, name)

    def bind_tools(self, tools, **kwargs):
        return FallbackLLM(
            self._primary.bind_tools(tools, **kwargs),
            self._fallback.bind_tools(tools, **kwargs),
        )

    def with_structured_output(self, schema, **kwargs):
        return FallbackLLM(
            self._primary.with_structured_output(schema, **kwargs),
            self._fallback.with_structured_output(schema, **kwargs),
        )

    def invoke(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            return self._primary.invoke(input, config=config, **kwargs)
        except Exception as e:
            logger.warning(
                "主模型 %s 调用失败 (%s: %s)，切换到备用模型 %s",
                self._primary.model_name, type(e).__name__, e, self._fallback.model_name,
            )
            return self._fallback.invoke(input, config=config, **kwargs)

    async def ainvoke(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            return await self._primary.ainvoke(input, config=config, **kwargs)
        except Exception as e:
            logger.warning(
                "主模型 %s 调用失败 (%s: %s)，切换到备用模型 %s",
                self._primary.model_name, type(e).__name__, e, self._fallback.model_name,
            )
            return await self._fallback.ainvoke(input, config=config, **kwargs)

    def stream(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            meaningful = False
            for chunk in self._primary.stream(input, config=config, **kwargs):
                meaningful = meaningful or has_meaningful_ai_output(chunk)
                yield chunk
            if not meaningful:
                raise RuntimeError("模型流式响应为空")
        except Exception as e:
            logger.warning(
                "主模型 %s 流式调用失败 (%s: %s)，切换到备用模型 %s 从头重流",
                self._primary.model_name, type(e).__name__, e, self._fallback.model_name,
            )
            yield from self._fallback.stream(input, config=config, **kwargs)

    async def astream(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            meaningful = False
            async for chunk in self._primary.astream(input, config=config, **kwargs):
                meaningful = meaningful or has_meaningful_ai_output(chunk)
                yield chunk
            if not meaningful:
                raise RuntimeError("模型流式响应为空")
        except Exception as e:
            logger.warning(
                "主模型 %s 流式调用失败 (%s: %s)，切换到备用模型 %s 从头重流",
                self._primary.model_name, type(e).__name__, e, self._fallback.model_name,
            )
            async for chunk in self._fallback.astream(input, config=config, **kwargs):
                yield chunk
