"""Deep Agents Supervisor 运行时；专职子 Agent 通过显式业务工具交接。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any
import uuid

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend, StateBackend
from deepagents.profiles import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, messages_from_dict, messages_to_dict
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

from services.message_content_utils import extract_tool_calls

from services.agents.novel_summarization import build_novel_summarization_middleware


DEEP_AGENT_CONTEXT_ROOT = Path(__file__).resolve().parents[3] / "data" / "deep_agent_context"
logger = logging.getLogger(__name__)


def _summarization_state_path(scope_kind: str, scope_id: str) -> Path:
    return DEEP_AGENT_CONTEXT_ROOT / scope_kind / scope_id / "summarization_state.json"


def save_summarization_state(scope_kind: str, scope_id: str, update: dict) -> None:
    """持久化 Deep Agents 的摘要事件，使下一次业务请求沿用同一压缩状态。"""
    event = update.get("_summarization_event")
    session_id = update.get("_summarization_session_id")
    if not isinstance(event, dict) or not isinstance(session_id, str):
        return
    summary_message = event.get("summary_message")
    if summary_message is None:
        return
    payload = {
        "cutoff_index": int(event["cutoff_index"]),
        "summary_message": messages_to_dict([summary_message])[0],
        "file_path": event.get("file_path"),
        "summarization_session_id": session_id,
    }
    path = _summarization_state_path(scope_kind, scope_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def load_summarization_state(scope_kind: str, scope_id: str) -> dict:
    path = _summarization_state_path(scope_kind, scope_id)
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary_message = messages_from_dict([payload["summary_message"]])[0]
    return {
        "_summarization_event": {
            "cutoff_index": int(payload["cutoff_index"]),
            "summary_message": summary_message,
            "file_path": payload.get("file_path"),
        },
        "_summarization_session_id": payload["summarization_session_id"],
    }


def build_context_backend(scope_kind: str | None, scope_id: str | None):
    """为一个业务会话创建隔离且可跨请求读取的虚拟文件后端。"""
    if not scope_kind or not scope_id:
        return StateBackend()
    root = DEEP_AGENT_CONTEXT_ROOT / scope_kind / scope_id
    root.mkdir(parents=True, exist_ok=True)
    return FilesystemBackend(root_dir=root, virtual_mode=True)


class AtomicToolMiddleware(AgentMiddleware):
    """串行执行工具，并让中断时仍可由 Supervisor 回滚当前工具。"""

    def __init__(self, *, work_id: str | None, session_id: str | None) -> None:
        self.work_id = work_id
        self.session_id = session_id
        self._lock = asyncio.Lock()

    async def awrap_tool_call(self, request, handler):
        from services.agents.supervisor import get_context
        from services.tool_execution_unit import ToolExecutionUnit

        async with self._lock:
            call_id = str(request.tool_call.get("id") or "")
            unit = ToolExecutionUnit.begin(
                work_id=self.work_id,
                session_id=self.session_id,
                tool_call_id=call_id,
            )
            context = get_context()
            context["active_tool_unit"] = unit
            result = await handler(request)
            if context.get("active_tool_unit") is unit:
                context["active_tool_unit"] = None
            return result


class RequireToolCallMiddleware(AgentMiddleware):
    """拒绝纯文本模型响应，并在同一内部上下文要求 Agent 继续或调用结束工具。"""

    def __init__(self, *, completion_tool_name: str, max_corrections: int = 2) -> None:
        self.completion_tool_name = completion_tool_name
        self.max_corrections = max_corrections

    def _has_tool_call(self, response: ModelResponse) -> bool:
        return any(
            isinstance(message, AIMessage) and bool(extract_tool_calls(message))
            for message in response.result
        )

    def _correction(self) -> HumanMessage:
        return HumanMessage(content=(
            f"必须使用 {self.completion_tool_name} 工具来结束任务；如果任务未完成则继续，"
            f"完成后使用 {self.completion_tool_name} 提交完整结果。"
        ))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        current = request
        for attempt in range(self.max_corrections + 1):
            response = await handler(current)
            if self._has_tool_call(response):
                return response
            logger.warning(
                "agent model response missing tool call attempt=%d required_tool=%s",
                attempt + 1, self.completion_tool_name,
            )
            if attempt == self.max_corrections:
                raise RuntimeError(
                    f"Agent 连续未调用工具；必须使用 {self.completion_tool_name} 结束任务"
                )
            current = current.override(
                messages=[*current.messages, *response.result, self._correction()]
            )
        raise AssertionError("unreachable")


DEEP_AGENT_FORBIDDEN_TOOLS = frozenset({
    "task",
    "ls",
    "write_file",
    "edit_file",
    "delete",
    "glob",
    "grep",
    "execute",
})

register_harness_profile(
    "novel",
    HarnessProfile(
        excluded_tools=DEEP_AGENT_FORBIDDEN_TOOLS,
        excluded_middleware=frozenset({"SummarizationMiddleware"}),
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
    ),
)


def build_deep_agent(
    *,
    model: BaseChatModel,
    tools: Sequence[Any],
    system_prompt: str,
    checkpointer=None,
    work_id: str | None = None,
    session_id: str | None = None,
    scope_kind: str | None = None,
    scope_id: str | None = None,
    atomic_tools: bool = True,
    completion_tool_name: str | None = None,
):
    """创建只暴露项目工具的 Deep Agents Supervisor。"""
    backend = build_context_backend(
        scope_kind or ("session" if session_id else None),
        scope_id or session_id,
    )
    persist_compaction = None
    if scope_kind and scope_id:
        persist_compaction = lambda update: save_summarization_state(scope_kind, scope_id, update)
    elif session_id:
        persist_compaction = lambda update: save_summarization_state("session", session_id, update)
    summarization, compact = build_novel_summarization_middleware(
        model, backend, on_compaction=persist_compaction,
    )
    middleware = [summarization, compact]
    if completion_tool_name:
        middleware.insert(0, RequireToolCallMiddleware(
            completion_tool_name=completion_tool_name,
        ))
    if atomic_tools:
        middleware.insert(0, AtomicToolMiddleware(work_id=work_id, session_id=session_id))
    return create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=system_prompt,
        middleware=middleware,
        backend=backend,
        subagents=[],  # 内置通用 task 保持关闭；Writer、Reviewer 通过显式业务工具调用。
        checkpointer=checkpointer,
        name="novel_supervisor",
    )
