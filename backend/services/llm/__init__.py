"""Novel LLM 基类：httpx 协议层 + LangChain 适配。

业务侧只通过 ``get_llm`` / ``create_provider`` / ``LLMChatService`` 访问模型，
禁止直接实例化协议客户端，也禁止绕过本包调用 ChatOpenAI。
"""
from services.llm.llm_service import (
    BaseLLMProvider,
    LLMChatService,
    create_llm_chat_service,
    create_provider,
)
from services.llm.llm_types import ChatMessage, LLMModelConfig
from services.llm.langchain_adapter import NovelLLM

__all__ = [
    "BaseLLMProvider",
    "ChatMessage",
    "LLMChatService",
    "LLMModelConfig",
    "NovelLLM",
    "create_llm_chat_service",
    "create_provider",
]
