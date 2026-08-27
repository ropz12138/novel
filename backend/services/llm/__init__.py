"""Novel LLM 基类：httpx 协议层 + LangChain 适配。

业务侧通过 ``services.agents.llm.get_llm`` 取模型；协议层入口是
``create_provider`` / ``NovelLLM``，禁止直接实例化协议客户端。
"""
from services.llm.llm_service import (
    BaseLLMProvider,
    create_provider,
)
from services.llm.llm_types import LLMModelConfig
from services.llm.langchain_adapter import NovelLLM

__all__ = [
    "BaseLLMProvider",
    "LLMModelConfig",
    "NovelLLM",
    "create_provider",
]
