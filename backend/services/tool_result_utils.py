"""工具返回内容是否表示成功。"""
from __future__ import annotations

import json


def tool_message_success(content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return True
    if "失败" in text[:24]:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return True
    if not isinstance(data, dict):
        return True
    if data.get("error"):
        return False
    if data.get("success") is False:
        return False
    return True


def lookup_tool_results_after(messages: list, start: int) -> dict[str, object]:
    """AIMessage 之后、下一条 AIMessage 之前的 ToolMessage，按 id/name 索引。"""
    results: dict[str, object] = {}
    for msg in messages[start:]:
        type_name = type(msg).__name__
        if type_name == "AIMessage":
            break
        if type_name != "ToolMessage":
            continue
        call_id = getattr(msg, "tool_call_id", "") or ""
        name = getattr(msg, "name", "") or ""
        if call_id:
            results[call_id] = msg
        if name:
            results[name] = msg
    return results
