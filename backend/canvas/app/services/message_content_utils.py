"""从 LangChain AIMessage 提取可持久化的文本与 tool_calls。"""
from __future__ import annotations

from typing import Any


def extract_text_content(content: Any) -> str:
    """将 AIMessage.content 规范为纯文本（支持 str 与 content blocks）。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    parts.append(str(block.get("text") or ""))
                elif "text" in block and block_type not in ("tool_call", "tool_use"):
                    parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content)


def extract_tool_calls(msg: Any) -> list[dict]:
    """从 AIMessage 提取 tool_calls（支持 tool_calls 属性与 content blocks）。"""
    seen: set[str] = set()
    calls: list[dict] = []

    def _add(call_id: str, name: str, args: dict) -> None:
        key = call_id or f"{name}:{len(calls)}"
        if key in seen:
            return
        seen.add(key)
        calls.append({"id": call_id, "name": name, "args": args or {}})

    for tc in getattr(msg, "tool_calls", None) or []:
        if not isinstance(tc, dict):
            continue
        _add(str(tc.get("id") or ""), str(tc.get("name") or ""), tc.get("args") or {})

    content = getattr(msg, "content", None)
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("tool_call", "tool_use"):
                _add(
                    str(block.get("id") or ""),
                    str(block.get("name") or ""),
                    block.get("args") or block.get("input") or {},
                )

    return calls
