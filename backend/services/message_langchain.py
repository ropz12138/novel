"""将 canvas supervisor_messages 记录还原为 LangChain 消息列表。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

_SKIP_TYPES_DEFAULT = frozenset({
    "requirements_todolist",
})


def db_message_dicts_to_langchain(
    db_messages: list[dict],
    *,
    skip_types: frozenset[str] | None = None,
) -> list[BaseMessage]:
    """从 supervisor_messages 字典列表构建 LangChain 消息，保留 tool 调用链。"""
    skip = skip_types or _SKIP_TYPES_DEFAULT
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
        role = m.get("role", "")
        meta = m.get("meta") if isinstance(m.get("meta"), dict) else {}

        if role == "user":
            flush_pending_tool_calls()
            langchain_messages.append(HumanMessage(content=m.get("content", "")))
            continue

        if role == "assistant":
            if meta.get("type") in skip:
                continue
            flush_pending_tool_calls()
            content = (m.get("content") or "").strip()
            if not content:
                continue
            ai_kwargs: dict[str, Any] = {"content": content}
            if meta.get("reasoning_content"):
                ai_kwargs["additional_kwargs"] = {"reasoning_content": meta["reasoning_content"]}
            langchain_messages.append(AIMessage(**ai_kwargs))
            continue

        if role == "tool_call":
            if not pending_tool_calls and meta.get("reasoning_content"):
                pending_reasoning = meta["reasoning_content"]
            pending_tool_calls.append({
                "name": m.get("content", ""),
                "args": meta.get("args") or {},
                "id": meta.get("tool_call_id") or f"call_{m.get('sort_order', 0)}",
            })
            continue

        if role == "tool_result":
            flush_pending_tool_calls()
            langchain_messages.append(
                ToolMessage(
                    content=m.get("content", ""),
                    tool_call_id=meta.get("tool_call_id") or "",
                    name=meta.get("tool_name"),
                )
            )

    pending_tool_calls = []
    pending_reasoning = None
    return langchain_messages
