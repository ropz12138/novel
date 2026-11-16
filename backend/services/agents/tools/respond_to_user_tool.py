"""Supervisor 结束工具：本轮给用户看的最终回复。"""
from __future__ import annotations

import json
import asyncio
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from services.agents.supervisor_turn import RESPOND_TO_USER_TOOL


class RespondToUserInput(BaseModel):
    completed_task_ids: list[str] = Field(default_factory=list, description="本条回复实际完成的任务编号，例如 T2；只填写已经完成的事项")
    outcome: Literal["completed", "needs_user", "needs_revision"] = Field(default="completed", description="本轮实际结果：完成、等待用户确认、已保存但仍需修订或核验。")
    message: str = Field(description="给用户看的最终回复全文。这就是用户看到的本轮答案，不是下一步行动宣言。")


def _respond_to_user(message: str, completed_task_ids: list[str] | None = None, outcome: str = "completed") -> str:
    return asyncio.run(_respond_and_complete(message, completed_task_ids, outcome))


def _pending_tasks(ctx):
    if not ctx.get("session_id"):
        return []
    from database import SessionLocal
    from services.todo_service import list_todo_items
    with SessionLocal() as db:
        return [
            {"task_id": item.task_id, "task": item.task, "status": item.status}
            for item in list_todo_items(db, ctx["session_id"])
            if item.status != "completed"
        ]


async def _respond_and_complete(message: str, completed_task_ids: list[str] | None = None, outcome: str = "completed") -> str:
    from services.agents.supervisor import get_context
    from services.agents.tools.todo_tools import _update_todolist_async
    result = {"success": True, "message": message}
    errors = []
    ctx = get_context()
    control = ctx.get("run_control")
    if control and (control.active() or control.ready()):
        return json.dumps({"success": False, "status": "running",
                           "error": "仍有子任务或新输入需要处理，请继续独立工作或调用 wait_for_subagents"}, ensure_ascii=False)
    for task_id in dict.fromkeys(completed_task_ids or []):
        completion = await _update_todolist_async("complete", task_id=task_id)
        if completion.startswith("失败"):
            errors.append({"task_id": task_id, "error": completion})
    pending = _pending_tasks(ctx)
    blocked = bool(errors) or (outcome == "completed" and ctx.get("todo_used_this_turn") and bool(pending))
    if blocked:
        result = {
            "success": False,
            "status": "needs_revision",
            "pending_tasks": pending,
            "recovery": {
                "action": "continue_tasks",
                "instruction": "完成本轮仍未结束的任务后以 completed 交付；需要作者选择时用 needs_user，阶段结果用 needs_revision。",
            },
        }
        if errors:
            result["task_completion_errors"] = errors
    else:
        result.update(status=outcome, pending_tasks=pending)
    if (ctx.get("work_id") and ctx.get("session_id")) or result["status"] != "completed":
        ctx["workflow_gate"] = {"passed": result["status"] == "completed", "status": result["status"], "code": "request_delivery"}
    if result.get("success") and ctx.get("session_id") and result["status"] in {"completed", "needs_user", "needs_revision"}:
        from services.session_store import session_store
        session_store.update_session(ctx["session_id"], status=result["status"])
    return json.dumps(result, ensure_ascii=False)


respond_to_user = StructuredTool.from_function(
    func=_respond_to_user, coroutine=_respond_and_complete,
    name=RESPOND_TO_USER_TOOL,
    return_direct=True,
    description=(
        "结束本轮并对用户说话。message 就是用户看到的最终回复。"
        "真正改画布、写章节、读节点时必须先调用对应工具；"
        "只有本轮工作已完成，或需要向用户提问/说明结果时，才调用本工具。"
        "禁止把「我先去改/让我更新」这类未执行的行动宣言作为 message。"
        "本轮若同时调用了其他工具，本工具会被忽略。"
    ),
    args_schema=RespondToUserInput,
)
