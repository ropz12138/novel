"""LLM工厂：一律经 NovelLLM / BaseLLMProvider。"""
import logging

from langchain_core.messages import AIMessage

from config import settings
from services.llm.factory import build_model_config, resolve_model_names
from services.llm.langchain_adapter import NovelLLM
from services.thinking_llm import FallbackLLM

logger = logging.getLogger(__name__)


def get_llm(
    temperature: float = 0.7,
    streaming: bool = True,
    model_name: str | None = None,
    primary: str | None = None,
    fallback: str | None = None,
):
    """获取 LLM 实例（BaseLLMProvider + 可选 FallbackLLM）。"""
    del streaming  # 传输始终走基类 stream_chat；保留参数以兼容调用方
    primary_name, fallback_name = resolve_model_names(primary, fallback, model_name=model_name)
    primary_llm = NovelLLM.from_configs(build_model_config(primary_name, temperature=temperature))
    if fallback_name:
        fallback_llm = NovelLLM.from_configs(build_model_config(fallback_name, temperature=temperature))
        wrapped = FallbackLLM(primary_llm, fallback_llm)
        return wrapped
    return primary_llm


def context_model_pref_kwargs() -> dict:
    """从 Supervisor 上下文读取用户主/备模型偏好，供工具内 get_llm 使用。"""
    from services.agents.supervisor import get_context
    pref = get_context().get("model_pref")
    if not pref:
        return {}
    return {"primary": pref.get("primary"), "fallback": pref.get("fallback")}


def bind_tools_to_llm(llm, tools: list):
    from services.llm_stream import bind_agent_llm_with_tools
    return bind_agent_llm_with_tools(llm, tools)


def should_continue(state: dict) -> str:
    last_message = state["messages"][-1]
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"
    return "end"
