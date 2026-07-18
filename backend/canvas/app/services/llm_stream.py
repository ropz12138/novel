"""LLM 流式输出工具 — 对齐 main 分支 sub_agent_base。"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable

from langchain_core.messages import AIMessage, AIMessageChunk

logger = logging.getLogger(__name__)

# DeepSeek / 兼容 API：启用 reasoning 流
AGENT_THINKING_EXTRA_BODY = {"thinking": {"type": "enabled"}}


def bind_agent_llm_with_tools(llm, tools):
    """绑定工具并启用 Thinking Mode。"""
    return llm.bind_tools(tools, extra_body=AGENT_THINKING_EXTRA_BODY)


def stream_text_delta(chunk: AIMessageChunk | AIMessage | None) -> str:
    """从 LLM 流式 chunk 取出正文增量。"""
    if chunk is None:
        return ""
    if getattr(chunk, "tool_call_chunks", None) and not (getattr(chunk, "content", None) or ""):
        return ""
    content = getattr(chunk, "content", None)
    if content is None or content == "":
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif isinstance(part, dict) and "text" in part and part.get("type") not in ("tool_call", "tool_use"):
                parts.append(str(part.get("text") or ""))
        return "".join(parts)
    return str(content)


def stream_reasoning_delta(chunk: AIMessageChunk | AIMessage | None) -> str:
    """从 LLM 流式 chunk 取出 reasoning_content 增量。"""
    if chunk is None:
        return ""
    rc = getattr(chunk, "additional_kwargs", {}).get("reasoning_content")
    if rc is None or rc == "":
        return ""
    return str(rc)


async def emit_llm_stream_deltas(
    emit: Callable[[str, dict], Awaitable[None]],
    stream_event: str,
    chunk: AIMessageChunk,
) -> None:
    """将 reasoning/content 增量推送到 SSE。"""
    reasoning_delta = stream_reasoning_delta(chunk)
    if reasoning_delta:
        await emit(stream_event, {"chunk": reasoning_delta, "phase": "reasoning"})
    content_delta = stream_text_delta(chunk)
    if content_delta:
        await emit(stream_event, {"chunk": content_delta, "phase": "content"})


def chunk_to_ai_message(full: AIMessageChunk | AIMessage) -> AIMessage:
    """将累计 AIMessageChunk 转为 AIMessage。"""
    if isinstance(full, AIMessage):
        return full
    raw_tc = list(full.tool_calls) if getattr(full, "tool_calls", None) else []
    tool_calls: list[dict[str, Any]] = []
    for idx, call in enumerate(raw_tc):
        call_id = call.get("id") or f"call_auto_{uuid.uuid4().hex[:12]}"
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        tool_calls.append({
            "name": call.get("name", ""),
            "args": args,
            "id": call_id,
            "type": call.get("type", "tool_call"),
        })
    kwargs: dict[str, Any] = {"content": full.content or "", "tool_calls": tool_calls}
    msg_id = getattr(full, "id", None)
    if msg_id:
        kwargs["id"] = msg_id
    rc = getattr(full, "additional_kwargs", {}).get("reasoning_content")
    if rc:
        kwargs["additional_kwargs"] = {"reasoning_content": rc}
    return AIMessage(**kwargs)
