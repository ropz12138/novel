"""Supervisor 单轮收口：按评审强度限制迭代，结束工具转为用户可见终态。"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from services.message_content_utils import extract_text_content, extract_tool_calls

RESPOND_TO_USER_TOOL = "respond_to_user"
MAX_SUPERVISOR_TURN_RETRIES = 2
SUPERVISOR_TOOL_CALL_LIMIT = 40
SUPERVISOR_GRAPH_RECURSION_LIMIT = 90
HIGH_SUPERVISOR_TOOL_CALL_LIMIT = 80
HIGH_SUPERVISOR_GRAPH_RECURSION_LIMIT = 200


def get_supervisor_iteration_limits(chapter_review_intensity: str) -> tuple[int, int]:
    if chapter_review_intensity == "high":
        return HIGH_SUPERVISOR_TOOL_CALL_LIMIT, HIGH_SUPERVISOR_GRAPH_RECURSION_LIMIT
    return SUPERVISOR_TOOL_CALL_LIMIT, SUPERVISOR_GRAPH_RECURSION_LIMIT

SUPERVISOR_TOOL_LIMIT_INSTRUCTION = """You have reached the maximum number of tool rounds for this turn.
Call respond_to_user now with a complete user-visible reply.
Summarize what was finished, what was not, and what the user can do next.
Do not call any other tool.
"""

SUPERVISOR_TURN_RETRY_INSTRUCTION = """Previous response was not a valid final answer.
Continue from the current state.
Do not describe the next action.
Execute it now.
Take the action.
Use tools if needed.
If the user should see a final reply, call respond_to_user with that full message.
"""

MAX_ANNOUNCEMENT_CHARS = 160

_ACTION_PHRASES = (
    "让我先",
    "让我来",
    "让我去",
    "让我更新",
    "让我修改",
    "让我调整",
    "让我修复",
    "让我重写",
    "让我精简",
    "让我开始执行",
    "让我重新",
    "我先去",
    "我先看",
    "我先读",
    "我先查",
    "我来调整",
    "我来修改",
    "我来更新",
    "let me check",
    "let me search",
    "let me look",
    "let me update",
    "let me fix",
    "i'll check",
    "i'll search",
    "i'll look",
    "i'll update",
    "i'll fix",
)

_DONE_MARKERS = (
    "已经",
    "已完成",
    "已更新",
    "已修改",
    "已调整",
    "改好了",
    "完成了",
    "写好了",
)


def is_short_action_announcement(text: str | None) -> bool:
    if not text:
        return False
    stripped = text.strip()
    if not stripped or len(stripped) > MAX_ANNOUNCEMENT_CHARS:
        return False
    if "##" in stripped:
        return False
    if any(marker in stripped for marker in _DONE_MARKERS):
        return False
    lowered = stripped.lower()
    for phrase in _ACTION_PHRASES:
        if phrase.isascii():
            if phrase in lowered:
                return True
        elif phrase in stripped:
            return True
    return False


def _ai_tool_names(message: AIMessage) -> list[str]:
    names: list[str] = []
    raw = getattr(message, "tool_calls", None) or []
    for tc in raw:
        if isinstance(tc, dict):
            names.append(str(tc.get("name") or ""))
        else:
            names.append(str(getattr(tc, "name", "") or ""))
    if not names:
        names = [str(tc.get("name") or "") for tc in extract_tool_calls(message)]
    return names


def count_supervisor_work_tool_calls(messages: list[BaseMessage]) -> int:
    calls = 0
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        names = _ai_tool_names(message)
        calls += sum(1 for name in names if name and name != RESPOND_TO_USER_TOOL)
    return calls


def count_current_run_work_tool_calls(
    messages: list[BaseMessage],
    run_start_count: int,
) -> int:
    """统计当前用户消息触发的工具调用，不让同 session 历史占用本轮额度。"""
    return max(0, count_supervisor_work_tool_calls(messages) - run_start_count)


def _tool_args(call: dict) -> dict:
    args = call.get("args") or {}
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return args if isinstance(args, dict) else {}


def _normalize_tool_calls(message: AIMessage) -> list[dict[str, Any]]:
    calls = extract_tool_calls(message)
    if calls:
        return calls
    raw = getattr(message, "tool_calls", None) or []
    normalized = []
    for tc in raw:
        if not isinstance(tc, dict):
            continue
        normalized.append({
            "id": tc.get("id") or "",
            "name": tc.get("name") or "",
            "args": tc.get("args") or {},
        })
    return normalized


def _clone_ai_message(message: AIMessage, *, content: str, tool_calls: list[dict]) -> AIMessage:
    kwargs: dict[str, Any] = {"content": content, "tool_calls": tool_calls}
    msg_id = getattr(message, "id", None)
    if msg_id:
        kwargs["id"] = msg_id
    usage = getattr(message, "usage_metadata", None)
    if usage:
        kwargs["usage_metadata"] = usage
    additional = getattr(message, "additional_kwargs", None) or {}
    if additional:
        kwargs["additional_kwargs"] = additional
    return AIMessage(**kwargs)


def prepare_supervisor_ai_message(message: AIMessage) -> tuple[str, AIMessage]:
    """把一轮模型输出收成 tools / end / retry。"""
    calls = _normalize_tool_calls(message)
    end_calls = [call for call in calls if call.get("name") == RESPOND_TO_USER_TOOL]
    other_calls = [call for call in calls if call.get("name") != RESPOND_TO_USER_TOOL]
    if other_calls:
        return "tools", _clone_ai_message(
            message,
            content=extract_text_content(message.content),
            tool_calls=other_calls,
        )
    if end_calls:
        reply = str(_tool_args(end_calls[0]).get("message") or "").strip()
        if not reply or is_short_action_announcement(reply):
            return "retry", message
        return "end", _clone_ai_message(message, content=reply, tool_calls=[])
    text = extract_text_content(message.content).strip()
    if text and not is_short_action_announcement(text):
        return "end", _clone_ai_message(message, content=text, tool_calls=[])
    return "retry", message
