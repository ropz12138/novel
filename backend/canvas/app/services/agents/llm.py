"""LLM工厂和工具函数"""
import logging
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.runnables import Runnable, RunnableConfig

from app.config import settings

logger = logging.getLogger(__name__)


class FallbackLLM(Runnable):
    """包装主模型和备用模型，遇到 429 时自动切换到备选模型重试。"""

    def __init__(self, primary: ChatOpenAI, fallback: ChatOpenAI):
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
            if self._is_rate_limit(e):
                logger.warning("429 rate limit, falling back to %s", self._fallback.model_name)
                return self._fallback.invoke(input, config=config, **kwargs)
            raise

    async def ainvoke(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            return await self._primary.ainvoke(input, config=config, **kwargs)
        except Exception as e:
            if self._is_rate_limit(e):
                logger.warning("429 rate limit, falling back to %s", self._fallback.model_name)
                return await self._fallback.ainvoke(input, config=config, **kwargs)
            raise

    def stream(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            yield from self._primary.stream(input, config=config, **kwargs)
        except Exception as e:
            if self._is_rate_limit(e):
                logger.warning("429 rate limit in stream, falling back to %s", self._fallback.model_name)
                yield from self._fallback.stream(input, config=config, **kwargs)
            else:
                raise

    async def astream(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            async for chunk in self._primary.astream(input, config=config, **kwargs):
                yield chunk
        except Exception as e:
            if self._is_rate_limit(e):
                logger.warning("429 rate limit in stream, falling back to %s", self._fallback.model_name)
                async for chunk in self._fallback.astream(input, config=config, **kwargs):
                    yield chunk
            else:
                raise

    @staticmethod
    def _is_rate_limit(e: Exception) -> bool:
        s = str(e).lower()
        return "429" in s or "rate" in s or "too many requests" in s


def get_llm(temperature: float = 0.7, streaming: bool = True, model_name: str | None = None):
    """获取LLM实例（带备用模型的重试机制）"""
    # 主模型
    primary_config = settings.get_model_config(model_name)
    primary = ChatOpenAI(
        model=model_name or settings.default_model,
        base_url=primary_config["base_url"],
        api_key=primary_config["api_key"],
        temperature=temperature,
        streaming=streaming,
    )

    # 备用模型
    if settings.fallback_model:
        fallback_config = settings.get_model_config(settings.fallback_model)
        fallback = ChatOpenAI(
            model=settings.fallback_model,
            base_url=fallback_config["base_url"],
            api_key=fallback_config["api_key"],
            temperature=temperature,
            streaming=streaming,
        )
        return FallbackLLM(primary, fallback)

    return primary


def bind_tools_to_llm(llm, tools: list):
    """绑定工具到LLM"""
    return llm.bind_tools(tools)


async def stream_llm_response(llm_with_tools, messages: list, emit=None, event_name: str = "thinking_stream"):
    """流式调用LLM并返回完整消息"""
    full_content = ""
    tool_calls = []

    async for chunk in llm_with_tools.astream(messages):
        if emit:
            await emit(event_name, {
                "content": chunk.content if hasattr(chunk, "content") else "",
            })

        if isinstance(chunk, AIMessageChunk):
            if chunk.content:
                full_content += chunk.content
            if chunk.tool_calls:
                tool_calls.extend(chunk.tool_calls)

    return AIMessage(content=full_content, tool_calls=tool_calls)


def should_continue(state: dict) -> str:
    """判断是否继续调用工具"""
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"
