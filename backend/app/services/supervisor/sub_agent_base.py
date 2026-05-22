"""子 Agent 公共基础框架

提供所有子 Agent 共享的 LangGraph 构建逻辑、状态定义和流式处理工具函数。
每个子 Agent 通过继承或组合使用这些基础设施，实现 Tool-Calling 能力。
"""

import logging
from typing import Any, Callable

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolNode
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── 流式处理工具函数 ──


def stream_text_delta(chunk: AIMessageChunk) -> str:
    """从 LLM 流式 chunk 取出正文增量；不展示纯 tool-call 分片。"""
    if chunk is None:
        return ""
    if getattr(chunk, "tool_call_chunks", None) and not (getattr(chunk, "content", None) or ""):
        return ""
    c = getattr(chunk, "content", None)
    if c is None or c == "":
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for part in c:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text") or ""))
            elif hasattr(part, "text"):
                parts.append(str(getattr(part, "text", "") or ""))
        return "".join(parts)
    return str(c)


def chunk_to_ai_message(full: AIMessageChunk | AIMessage) -> AIMessage:
    """将累计的 AIMessageChunk 转为 AIMessage，供 LangGraph 状态与 tool 路由使用。"""
    if isinstance(full, AIMessage):
        return full
    tc = list(full.tool_calls) if getattr(full, "tool_calls", None) else []
    kwargs: dict[str, Any] = {"content": full.content or "", "tool_calls": tc}
    _id = getattr(full, "id", None)
    if _id:
        kwargs["id"] = _id
    return AIMessage(**kwargs)


# ── LLM 工厂 ──


def get_llm(temperature: float = 0.7, streaming: bool = True, *, model_name: str | None = None) -> ChatOpenAI:
    """创建子 Agent 使用的 LLM 实例。

    Args:
        temperature: 生成温度
        streaming: 是否启用流式输出
        model_name: 模型名称，不传则使用 default_model
    """
    name = model_name or settings.default_model
    model_conf = settings.get_model_config(model_name)
    return ChatOpenAI(
        model=name,
        api_key=model_conf["api_key"],
        base_url=model_conf["base_url"],
        temperature=temperature,
        streaming=streaming,
        request_timeout=(15, 180),
        max_retries=0,
    )


# ── 条件边 ──


def should_continue(state: dict) -> str:
    """条件边：判断 LLM 是否还在调用工具。"""
    messages = state.get("messages", [])
    if not messages:
        return END
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# ── Graph 构建器 ──


def build_sub_agent_graph(
    tools: list,
    state_class: type,
    agent_node_fn: Callable,
) -> StateGraph:
    """构建子 Agent 的 LangGraph StateGraph。

    Args:
        tools: 子 Agent 可用的工具列表
        state_class: 状态类（需继承 MessagesState）
        agent_node_fn: 异步 agent 节点函数，签名为 async def(state) -> dict

    Returns:
        编译后的 StateGraph
    """
    graph = StateGraph(state_class)
    graph.add_node("agent", agent_node_fn)
    graph.add_node("tools", ToolNode(tools))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


# ── 流式执行辅助 ──


async def run_agent_stream(
    llm_with_tools,
    messages: list[BaseMessage],
    emit: Callable | None = None,
    stream_event: str = "sub_agent_stream",
) -> AIMessage:
    """执行子 Agent 的 LLM 流式调用，聚合结果并返回完整 AIMessage。

    Args:
        llm_with_tools: 绑定了工具的 LLM 实例
        messages: 完整消息列表（含 system message）
        emit: SSE 事件发射回调，可为 None
        stream_event: 流式事件的名称

    Returns:
        完整的 AIMessage
    """
    aggregated: AIMessageChunk | None = None

    async for chunk in llm_with_tools.astream(messages):
        aggregated = chunk if aggregated is None else aggregated + chunk

        delta = stream_text_delta(chunk)
        if delta and emit:
            emit(stream_event, {"chunk": delta})

    if aggregated is None:
        raise RuntimeError("子 Agent LLM 未返回任何流式分片")

    return chunk_to_ai_message(aggregated)
