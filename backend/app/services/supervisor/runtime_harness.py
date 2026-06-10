"""Supervisor Runtime Harness — 统一运行时控制层

包含：
- Run Lifecycle Harness (Phase 7)
- Context Harness (Phase 8)
- Tool Policy Harness (Phase 9)
- Child Agent Harness (Phase 10)
- Recovery Harness (Phase 11)
- Observability Harness (Phase 12)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════
# Phase 7: Run Lifecycle Harness
# ═══════════════════════════════════════════════════════════════


class SupervisorRuntimeHarness:
    """统一管理一次 Supervisor 运行的生命周期"""

    def before_run(
        self,
        *,
        session: Any,
        user_message: str,
    ) -> dict:
        """运行前：生成 run_id，构建上下文，记录事件"""
        run_id = f"run-{uuid.uuid4().hex[:12]}"

        run_ctx = {
            "run_id": run_id,
            "session_id": session.id,
            "work_id": getattr(session, "work_id", None),
            "user_id": getattr(session, "user_id", None),
            "user_message": user_message,
            "ready_to_execute": getattr(session, "ready_to_execute", False),
            "started_at": _utcnow().isoformat(),
        }

        logger.info(
            "runtime_harness.before_run run_id=%s session_id=%s",
            run_id, session.id,
        )

        return run_ctx

    def after_run(
        self,
        *,
        session: Any,
        run_ctx: dict,
        db: Session,
        emit: Callable[[str, dict], None],
    ) -> None:
        """运行后：reconciliation，记录完成事件"""
        from app.services.supervisor.todo_harness import reconcile_stale_tasks

        reconcile_stale_tasks(
            session_id=session.id,
            db=db,
            stale_threshold_minutes=30,
            emit=emit,
        )

        emit("run_completed", {
            "run_id": run_ctx["run_id"],
            "session_id": session.id,
            "elapsed_hint": "completed",
        })

        logger.info(
            "runtime_harness.after_run run_id=%s session_id=%s",
            run_ctx["run_id"], session.id,
        )

    def on_error(
        self,
        *,
        session: Any,
        run_ctx: dict,
        exc: Exception,
        db: Session,
        emit: Callable[[str, dict], None],
    ) -> None:
        """运行异常：标记错误，reconciliation，记录失败事件"""
        from app.services.supervisor.todo_harness import reconcile_stale_tasks

        reconcile_stale_tasks(
            session_id=session.id,
            db=db,
            stale_threshold_minutes=30,
            emit=emit,
        )

        emit("run_failed", {
            "run_id": run_ctx["run_id"],
            "session_id": session.id,
            "error": str(exc),
        })

        logger.exception(
            "runtime_harness.on_error run_id=%s session_id=%s error=%s",
            run_ctx["run_id"], session.id, exc,
        )


# ═══════════════════════════════════════════════════════════════
# Phase 8: Context Harness
# ═══════════════════════════════════════════════════════════════


def build_supervisor_runtime_context(
    *,
    session_id: str,
    db: Session,
) -> str:
    """构建运行时上下文摘要，注入 Supervisor

    包含：session 状态、todolist 摘要、下一条可执行任务
    """
    from app.models.agent_model import SupervisorSession
    from app.models.task_item_model import TaskItem
    from app.services.supervisor.todo_harness import (
        get_next_executable_task,
        serialize_task_item,
    )

    session = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not session:
        return ""

    # 作品摘要
    work_summary = ""
    if session.work_id:
        from app.models.work_model import Work
        work = db.query(Work).filter_by(id=session.work_id).first()
        if work:
            work_summary = f"作品: {work.title}"

    # todolist 摘要
    tasks = (
        db.query(TaskItem)
        .filter_by(session_id=session_id)
        .order_by(TaskItem.sort_order)
        .all()
    )

    status_counts = {}
    for t in tasks:
        status_counts[t.status] = status_counts.get(t.status, 0) + 1

    todolist_summary = f"任务总数: {len(tasks)}"
    for status, count in sorted(status_counts.items()):
        todolist_summary += f", {status}: {count}"

    # 下一条可执行任务
    next_task = get_next_executable_task(session_id=session_id, db=db)
    next_task_info = ""
    if next_task:
        next_task_info = (
            f"\n下一条可执行任务: T{next_task.task_id} - {next_task.task_description}"
            f" (owner: {next_task.owner}, tool: {next_task.dispatch_tool or 'N/A'})"
        )

    # active_child 摘要
    active_child_info = ""
    if session.active_child:
        child = session.active_child
        active_child_info = f"\n当前等待确认: {child.get('type', 'unknown')}"

    lines = [
        "## 运行时上下文",
        f"会话状态: {session.status}",
        f"可执行: {'是' if session.ready_to_execute else '否'}",
    ]
    if work_summary:
        lines.append(work_summary)
    lines.append(todolist_summary)
    if next_task_info:
        lines.append(next_task_info)
    if active_child_info:
        lines.append(active_child_info)

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# Phase 9: Tool Policy Harness
# ═══════════════════════════════════════════════════════════════

DISPATCH_TOOLS = {"dispatch_outline", "dispatch_chapter", "dispatch_evaluation"}
POLICY_EXEMPT_TOOLS = {
    "execute_todo_task", "read_todolist", "analyze_requirements",
    "update_task_status", "update_todolist_readiness",
    "query_characters", "query_chapters", "query_chapter_meta",
    "grep_chapter_meta", "grep", "read_outline", "read_chapter",
    "query_characters_by_chapter", "grep_in_chapter",
    "query_chapter_outline", "query_outline_related_chapters",
    "query_previous_chapters",
    "read_work_context", "read_chat_history",
    "dispatch_requirements_planner",
}


def validate_tool_call_policy(
    *,
    tool_name: str,
    tool_args: dict,
    session_id: str,
    db: Session,
) -> dict:
    """检查工具调用是否符合策略

    第一阶段：只记录 warning，不拦截
    """
    result = {
        "allowed": True,
        "warning": "",
        "reason": "",
        "suggested_tool": "",
        "suggested_args": {},
    }

    # 非派发工具一律放行
    if tool_name not in DISPATCH_TOOLS:
        return result

    # 检查是否存在 pending todolist
    from app.models.agent_model import SupervisorSession
    from app.models.task_item_model import TaskItem

    session = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not session or not session.ready_to_execute:
        return result

    pending_tasks = (
        db.query(TaskItem)
        .filter_by(session_id=session_id, status="pending")
        .count()
    )

    if pending_tasks > 0:
        result["warning"] = (
            f"当前会话有 {pending_tasks} 条 pending 任务，"
            f"建议使用 execute_todo_task 而非直接调用 {tool_name}。"
        )
        result["reason"] = "pending_todolist_exists"
        result["suggested_tool"] = "execute_todo_task"

    return result


# ═══════════════════════════════════════════════════════════════
# Phase 10: Child Agent Harness
# ═══════════════════════════════════════════════════════════════


def set_active_child(
    *,
    session: Any,
    child_type: str,
    payload: dict,
    task_item_id: str | None = None,
    db: Session,
) -> None:
    """统一设置 active_child"""
    child = {
        "type": child_type,
        "task_item_id": task_item_id,
        "created_at": _utcnow().isoformat(),
        "status": "waiting_user",
    }
    child.update(payload)

    session.active_child = child
    session.status = "waiting"
    session.stage = "executing"

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def clear_active_child(
    *,
    session: Any,
    db: Session,
) -> None:
    """清理 active_child"""
    session.active_child = None

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


# ═══════════════════════════════════════════════════════════════
# Phase 11: Recovery Harness
# ═══════════════════════════════════════════════════════════════


def recover_session_on_resume(
    *,
    session_id: str,
    db: Session,
    emit: Callable[[str, dict], None],
) -> dict:
    """resume 时执行恢复逻辑

    策略：
    - waiting + active_child → 保持
    - running + no active_child + stale tasks → 修复
    """
    from app.models.agent_model import SupervisorSession
    from app.models.task_item_model import TaskItem
    from app.services.supervisor.todo_harness import reconcile_stale_tasks

    session = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not session:
        return {"recovered": False, "reason": "session_not_found"}

    # waiting session 保持不变
    if session.status == "waiting" and session.active_child:
        return {"recovered": False, "reason": "waiting_intact"}

    # 执行 stale task 修复
    result = reconcile_stale_tasks(
        session_id=session_id,
        db=db,
        stale_threshold_minutes=30,
        emit=emit,
    )

    recovered = result["reconciled"] > 0

    if recovered:
        logger.info(
            "recovery_harness recovered session_id=%s reconciled=%d",
            session_id, result["reconciled"],
        )

    return {"recovered": recovered, "reconciled": result["reconciled"]}


# ═══════════════════════════════════════════════════════════════
# Phase 12: Observability Harness
# ═══════════════════════════════════════════════════════════════


def log_run_event(
    *,
    session_id: str,
    run_id: str,
    event_type: str,
    db: Session,
    payload: dict | None = None,
) -> None:
    """记录运行事件到 messages 表

    使用 supervisor_runtime_event meta 格式
    """
    from app.routers.supervisor_router import persist_event_message

    data = {
        "run_id": run_id,
        "event": event_type,
        "payload": payload or {},
    }

    persist_event_message(db, session_id, "supervisor_runtime_event", data)
