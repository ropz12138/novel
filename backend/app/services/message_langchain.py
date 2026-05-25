"""将 DB messages 表记录还原为 LangChain 消息列表（含 Thinking Mode 所需字段）。"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.models.message_model import Message

_NO_CONTEXT_TYPES_DEFAULT = frozenset({
    "process_note",
    "edit_diff_card",
    "outline_diff_card",
    "character_diff_card",
})


def db_messages_to_langchain(
    db_messages: list[Message],
    *,
    skip_types: frozenset[str] | None = None,
) -> list[BaseMessage]:
    """从 messages 表构建 LangChain 消息，保留 reasoning_content 与 tool 调用链。"""
    skip = skip_types or _NO_CONTEXT_TYPES_DEFAULT
    langchain_messages: list[BaseMessage] = []
    pending_tool_calls: list[dict[str, Any]] = []
    pending_reasoning: str | None = None

    def flush_pending_tool_calls() -> None:
        nonlocal pending_tool_calls, pending_reasoning
        if not pending_tool_calls:
            return
        ai_kwargs: dict[str, Any] = {
            "content": "",
            "tool_calls": pending_tool_calls,
        }
        if pending_reasoning:
            ai_kwargs["additional_kwargs"] = {"reasoning_content": pending_reasoning}
        langchain_messages.append(AIMessage(**ai_kwargs))
        pending_tool_calls = []
        pending_reasoning = None

    for m in db_messages:
        if m.role == "user":
            flush_pending_tool_calls()
            langchain_messages.append(HumanMessage(content=m.content))
            continue

        if m.role == "assistant":
            meta = m.meta if isinstance(m.meta, dict) else {}
            if meta.get("type") in skip:
                continue
            flush_pending_tool_calls()
            content = (m.content or "").strip()
            if not content:
                continue
            ai_kwargs: dict[str, Any] = {"content": content}
            if meta.get("reasoning_content"):
                ai_kwargs["additional_kwargs"] = {"reasoning_content": meta["reasoning_content"]}
            langchain_messages.append(AIMessage(**ai_kwargs))
            continue

        if m.role == "tool_call":
            meta = m.meta if isinstance(m.meta, dict) else {}
            if not pending_tool_calls and meta.get("reasoning_content"):
                pending_reasoning = meta["reasoning_content"]
            pending_tool_calls.append({
                "name": m.content,
                "args": meta.get("args") or {},
                "id": meta.get("tool_call_id") or f"call_{m.sort_order}",
            })
            continue

        if m.role == "tool_result":
            flush_pending_tool_calls()
            meta = m.meta if isinstance(m.meta, dict) else {}
            langchain_messages.append(
                ToolMessage(
                    content=m.content,
                    tool_call_id=meta.get("tool_call_id") or "",
                    name=meta.get("tool_name"),
                )
            )

    # 末尾的 flush_pending_tool_calls 可能产生没有后续 ToolMessage 的 AIMessage(tool_calls)，
    # 这会导致 API 报错 "must be followed by tool messages"，
    # 所以末尾的 pending tool_calls 不再 flush，直接丢弃。
    # 正常的 tool_call → tool_result 链已在循环内部 flush 完毕。
    pending_tool_calls = []
    pending_reasoning = None

    return langchain_messages
