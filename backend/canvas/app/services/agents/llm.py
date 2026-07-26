"""LLM工厂和工具函数"""
import logging

from langchain_core.messages import AIMessage, AIMessageChunk

from app.config import settings
from app.services.thinking_llm import FallbackLLM, ThinkingChatOpenAI

logger = logging.getLogger(__name__)


def get_llm(
    temperature: float = 0.7,
    streaming: bool = True,
    model_name: str | None = None,
    primary: str | None = None,
    fallback: str | None = None,
):
    """获取 LLM 实例（带备用模型的重试机制）

    primary/fallback：用户级偏好覆盖；为 None 时回退 config 默认。
    """
    primary_name = primary or model_name or settings.default_model
    primary_config = settings.get_model_config(primary_name)
    primary_llm = ThinkingChatOpenAI(
        model=primary_name,
        base_url=primary_config["base_url"],
        api_key=primary_config["api_key"],
        temperature=temperature,
        streaming=streaming,
    )
    primary_llm._extra_body = primary_config.get("extra_body")

    fallback_name = fallback if fallback is not None else settings.fallback_model

    if fallback_name:
        fallback_config = settings.get_model_config(fallback_name)
        fallback_llm = ThinkingChatOpenAI(
            model=fallback_name,
            base_url=fallback_config["base_url"],
            api_key=fallback_config["api_key"],
            temperature=temperature,
            streaming=streaming,
        )
        fallback_llm._extra_body = fallback_config.get("extra_body")
        return FallbackLLM(primary_llm, fallback_llm)

    return primary_llm


def context_model_pref_kwargs() -> dict:
    """从 Supervisor 上下文读取用户主/备模型偏好，供工具内 get_llm 使用。"""
    try:
        from app.services.agents.supervisor import get_context
        pref = get_context().get("model_pref")
        if not pref:
            return {}
        return {"primary": pref.get("primary"), "fallback": pref.get("fallback")}
    except Exception:
        return {}


def bind_tools_to_llm(llm, tools: list):
    """绑定工具到 LLM，并启用 Thinking Mode（reasoning 流）。"""
    from app.services.llm_stream import bind_agent_llm_with_tools
    return bind_agent_llm_with_tools(llm, tools)


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
