"""子 Agent 公共基础框架

提供所有子 Agent 共享的 LangGraph 构建逻辑、状态定义和流式处理工具函数。
每个子 Agent 通过继承或组合使用这些基础设施，实现 Tool-Calling 能力。
"""

import logging
import uuid
from typing import Any, Callable

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from app.core.deepseek_llm import DeepSeekChatOpenAI, FallbackLLM
from langgraph.graph import END, START, StateGraph
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolNode
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.stream_trace import gap_log, gap_trace_from_config

logger = logging.getLogger(__name__)


# ── Thinking Mode（tool-calling Agent 节点启用 reasoning 流） ──

AGENT_THINKING_EXTRA_BODY = {"thinking": {"type": "enabled"}}


def bind_agent_llm_with_tools(llm, tools):
    """绑定工具并启用 Thinking Mode（覆盖 DeepSeek 默认 disabled）。"""
    return llm.bind_tools(tools, extra_body=AGENT_THINKING_EXTRA_BODY)


async def astream_agent_llm_to_message(
    llm_with_tools,
    messages: list[BaseMessage],
    *,
    emit: Callable[[str, dict], None] | None = None,
    stream_event: str = "thinking_stream",
) -> AIMessage:
    """Agent 节点 LLM 流式调用：推送 reasoning/content 并返回完整 AIMessage。"""
    aggregated: AIMessageChunk | None = None

    async for chunk in llm_with_tools.astream(messages):
        aggregated = chunk if aggregated is None else aggregated + chunk
        if emit:
            emit_llm_stream_deltas(emit, stream_event, chunk)

    if aggregated is None:
        raise RuntimeError("Agent LLM 未返回任何流式分片")

    return chunk_to_ai_message(aggregated)


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


def stream_reasoning_delta(chunk: AIMessageChunk) -> str:
    """从 LLM 流式 chunk 取出 reasoning_content 增量。"""
    if chunk is None:
        return ""
    rc = getattr(chunk, "additional_kwargs", {}).get("reasoning_content")
    if rc is None or rc == "":
        return ""
    return str(rc)


def emit_llm_stream_deltas(
    emit: Callable[[str, dict], None],
    stream_event: str,
    chunk: AIMessageChunk,
) -> None:
    """将单个 chunk 的 reasoning/content 增量推送到 SSE（先 reasoning 后 content）。"""
    reasoning_delta = stream_reasoning_delta(chunk)
    if reasoning_delta:
        emit(stream_event, {"chunk": reasoning_delta, "phase": "reasoning"})
    content_delta = stream_text_delta(chunk)
    if content_delta:
        emit(stream_event, {"chunk": content_delta, "phase": "content"})


async def stream_chain_with_reasoning(
    chain,
    inputs: dict,
    emit: Callable[[str, dict], None],
    stream_event: str,
    *,
    config: RunnableConfig | None = None,
    trace_label: str | None = None,
    should_abort: Callable[[], bool] | None = None,
) -> str:
    """流式执行 prompt|llm chain，推送 reasoning/content 并返回完整正文。"""
    from app.services.supervisor.session_interrupt import SessionInterruptedError

    trace_t0, trace_session_id = gap_trace_from_config(config)
    if trace_label:
        gap_log(
            "llm_chain_stream_begin",
            session_id=trace_session_id,
            t0=trace_t0,
            label=trace_label,
            stream_event=stream_event,
        )
    raw_output = ""
    first_chunk_logged = False
    async for chunk in chain.astream(inputs):
        if should_abort and should_abort():
            raise SessionInterruptedError("任务已被用户中断")
        if trace_label and not first_chunk_logged:
            first_chunk_logged = True
            gap_log(
                "llm_chain_first_chunk",
                session_id=trace_session_id,
                t0=trace_t0,
                label=trace_label,
                stream_event=stream_event,
            )
        emit_llm_stream_deltas(emit, stream_event, chunk)
        content_delta = stream_text_delta(chunk)
        if content_delta:
            raw_output += content_delta
    return raw_output


def chunk_to_ai_message(full: AIMessageChunk | AIMessage) -> AIMessage:
    """将累计的 AIMessageChunk 转为 AIMessage，供 LangGraph 状态与 tool 路由使用。"""
    if isinstance(full, AIMessage):
        return full
    raw_tc = list(full.tool_calls) if getattr(full, "tool_calls", None) else []
    tc: list[dict[str, Any]] = []
    for idx, call in enumerate(raw_tc):
        call_id = call.get("id")
        if not call_id:
            call_id = f"call_auto_{uuid.uuid4().hex[:12]}"
            logger.warning(
                "chunk_to_ai_message missing tool_call id; generated id=%s name=%s idx=%s",
                call_id,
                call.get("name"),
                idx,
            )
        args = call.get("args")
        if not isinstance(args, dict):
            args = {}
        tc.append(
            {
                "name": call.get("name", ""),
                "args": args,
                "id": call_id,
                "type": call.get("type", "tool_call"),
            }
        )
    kwargs: dict[str, Any] = {"content": full.content or "", "tool_calls": tc}
    _id = getattr(full, "id", None)
    if _id:
        kwargs["id"] = _id
    rc = getattr(full, "additional_kwargs", {}).get("reasoning_content")
    if rc:
        kwargs["additional_kwargs"] = {"reasoning_content": rc}
    return AIMessage(**kwargs)


# ── LLM 工厂 ──


def get_llm(temperature: float = 0.7, streaming: bool = True, *, model_name: str | None = None) -> DeepSeekChatOpenAI | FallbackLLM:
    """创建子 Agent 使用的 LLM 实例。

    Args:
        temperature: 生成温度
        streaming: 是否启用流式输出
        model_name: 模型名称，不传则使用 default_model

    Returns:
        当配置了 fallback_model 时返回 FallbackLLM（429 自动切换），
        否则返回 DeepSeekChatOpenAI。
    """
    name = model_name or settings.default_model
    model_conf = settings.get_model_config(model_name)
    primary = DeepSeekChatOpenAI(
        model=name,
        api_key=model_conf["api_key"],
        base_url=model_conf["base_url"],
        temperature=temperature,
        streaming=streaming,
        request_timeout=(15, 180),
        max_retries=0,
    )
    if settings.fallback_model:
        fb_conf = settings.get_model_config(settings.fallback_model)
        fallback = DeepSeekChatOpenAI(
            model=settings.fallback_model,
            api_key=fb_conf["api_key"],
            base_url=fb_conf["base_url"],
            temperature=temperature,
            streaming=streaming,
            request_timeout=(15, 180),
            max_retries=0,
        )
        return FallbackLLM(primary, fallback)
    return primary


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

        if emit:
            emit_llm_stream_deltas(emit, stream_event, chunk)

    if aggregated is None:
        raise RuntimeError("子 Agent LLM 未返回任何流式分片")

    return chunk_to_ai_message(aggregated)
