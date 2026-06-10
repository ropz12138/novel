"""Supervisor SSE router — 统一 Agent 入口"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.auth import get_current_user
from app.core.database import SessionLocal, get_db
from app.models.work_model import User, Work
from app.schemas.supervisor_schema import SupervisorStartRequest, SupervisorResumeRequest, SupervisorConfirmRequest, SupervisorInterruptRequest
from app.services.supervisor.supervisor_agent import SupervisorAgent
from app.services.agent_log_service import log_event, new_session_id
from app.services import message_service

from app.services.stream_trace import gap_log, gap_log_sse_emit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/supervisor", tags=["supervisor"])
_RUN_TASKS: set[asyncio.Task] = set()

PERSISTABLE_EVENTS = frozenset({
    "stage_start",
    "evaluation_done",
    "edit_chapter_diff",
    "edit_chapter_auto_applied",
    "outline_edit_diff",
    "character_edit_diff",
    "chapter_metadata_diff",
    "chapter_metadata_generated",
    "todolist_generated",
    "subtasks_created",
    "task_status_updated",
    "todolist_readiness_updated",
    "supervisor_runtime_event",
    "todolist_task_added",
    "todolist_task_edited",
    "todolist_task_deleted",
})


def persist_event_message(db: Session, session_id: str, event: str, data: dict) -> bool:
    """将 SSE 事件持久化为 messages 表中的一条记录。

    Returns True if a message was created, False otherwise.
    """
    from app.models.agent_model import SupervisorSession

    sess = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not sess:
        return False
    next_order = message_service.get_next_sort_order(db, session_id)

    if event == "stage_start":
        stage = data.get("stage")
        label = data.get("label") or data.get("stage") or "处理中"
        message_service.create_message(
            db,
            session_id=session_id,
            role="assistant",
            content=f"阶段：{label}",
            work_id=sess.work_id,
            sort_order=next_order,
            meta={"type": "process_note", "event": event, "stage": stage, "label": label},
        )
        return True

    if event == "evaluation_done":
        editor = data.get("editor", {}) or {}
        reader = data.get("reader", {}) or {}
        sync = data.get("sync", {}) or {}
        text = (
            f"章节评估完成：编辑 {editor.get('total_score', '-')} /60，"
            f"读者 {reader.get('total_score', '-')} /60，"
            f"同步 {sync.get('sync_score', '-')} /100（{sync.get('action_hint', '-')})"
        )
        message_service.create_message(
            db,
            session_id=session_id,
            role="assistant",
            content=text,
            work_id=sess.work_id,
            sort_order=next_order,
            meta={"type": "process_note", "event": event, "payload": data},
        )
        return True

    if event in ("edit_chapter_diff", "edit_chapter_auto_applied"):
        card = {
            "chapter_number": data.get("chapter_number"),
            "summary": data.get("summary", {}),
            "diff": data.get("diff", []),
            "new_content": data.get("new_content", ""),
            "readonly": event == "edit_chapter_auto_applied",
        }
        message_service.create_message(
            db,
            session_id=session_id,
            role="assistant",
            content="",
            work_id=sess.work_id,
            sort_order=next_order,
            meta={"type": "edit_diff_card", "event": event, "diffCard": card},
        )
        return True

    if event == "outline_edit_diff":
        message_service.create_message(
            db,
            session_id=session_id,
            role="assistant",
            content="",
            work_id=sess.work_id,
            sort_order=next_order,
            meta={
                "type": "outline_diff_card",
                "event": event,
                "outlineDiffCard": {
                    "diff": data.get("diff"),
                    "summary": data.get("summary"),
                    "message": data.get("message"),
                    "operations": data.get("operations"),
                    "readonly": bool(data.get("readonly")),
                },
            },
        )
        return True

    if event == "character_edit_diff":
        message_service.create_message(
            db,
            session_id=session_id,
            role="assistant",
            content="",
            work_id=sess.work_id,
            sort_order=next_order,
            meta={
                "type": "character_diff_card",
                "event": event,
                "characterDiffCard": {
                    "diff": data.get("diff"),
                    "summary": data.get("summary"),
                    "readonly": bool(data.get("readonly")),
                },
            },
        )
        return True

    if event == "chapter_metadata_diff":
        message_service.create_message(
            db,
            session_id=session_id,
            role="assistant",
            content="",
            work_id=sess.work_id,
            sort_order=next_order,
            meta={
                "type": "metadata_diff_card",
                "event": event,
                "metadataDiffCard": {
                    "chapter_number": data.get("chapter_number"),
                    "summary": data.get("summary", ""),
                    "key_plot_points": data.get("key_plot_points", []),
                    "diff": data.get("diff", {}),
                    "diff_summary": data.get("diff_summary", {}),
                },
            },
        )
        return True

    if event == "chapter_metadata_generated":
        message_service.create_message(
            db,
            session_id=session_id,
            role="assistant",
            content="",
            work_id=sess.work_id,
            sort_order=next_order,
            meta={
                "type": "chapter_meta_card",
                "event": event,
                "chapterMetaCard": {
                    "chapter_number": data.get("chapter_number"),
                    "summary": data.get("summary", ""),
                    "key_plot_points": data.get("key_plot_points", []),
                },
            },
        )
        return True

    if event == "todolist_generated":
        message_service.create_message(
            db,
            session_id=session_id,
            role="assistant",
            content="",
            work_id=sess.work_id,
            sort_order=next_order,
            meta={
                "type": "requirements_todolist",
                "event": event,
                "todoCard": {
                    "intent_summary": data.get("intent_summary", ""),
                    "todolist": data.get("todolist", []),
                    "ready_to_execute": data.get("ready_to_execute", False),
                },
            },
        )
        return True

    if event == "subtasks_created":
        all_msgs = message_service.get_messages_by_session(db, session_id)
        existing_msg = None
        for m in reversed(all_msgs):
            if (
                m.role == "assistant"
                and m.meta
                and m.meta.get("type") == "requirements_todolist"
                and m.meta.get("todoCard")
            ):
                existing_msg = m
                break

        if not existing_msg:
            return False

        todo_card = existing_msg.meta.get("todoCard", {})
        todolist = todo_card.setdefault("todolist", [])
        known_ids = {t.get("db_id") for t in todolist if isinstance(t, dict)}
        for subtask in data.get("subtasks", []):
            if subtask.get("db_id") not in known_ids:
                todolist.append(subtask)
                known_ids.add(subtask.get("db_id"))
        flag_modified(existing_msg, "meta")
        db.commit()
        return True

    if event == "task_status_updated":
        # 方案 B：原地更新最近一条 requirements_todolist message 中对应任务的状态
        all_msgs = message_service.get_messages_by_session(db, session_id)
        existing_msg = None
        for m in reversed(all_msgs):
            if (
                m.role == "assistant"
                and m.meta
                and m.meta.get("type") == "requirements_todolist"
                and m.meta.get("todoCard")
            ):
                existing_msg = m
                break

        if not existing_msg:
            return False

        todo_card = existing_msg.meta.get("todoCard", {})
        todolist = todo_card.get("todolist", [])
        target_id = data.get("task_item_id")
        updated = False
        for t in todolist:
            if t.get("db_id") == target_id:
                t["status"] = data.get("new_status", t.get("status"))
                if data.get("result_summary"):
                    t["result_summary"] = data["result_summary"]
                if data.get("error_message"):
                    t["error_message"] = data["error_message"]
                updated = True
                break

        if updated:
            flag_modified(existing_msg, "meta")
            db.commit()
        return True

    if event == "todolist_readiness_updated":
        all_msgs = message_service.get_messages_by_session(db, session_id)
        existing_msg = None
        for m in reversed(all_msgs):
            if (
                m.role == "assistant"
                and m.meta
                and m.meta.get("type") == "requirements_todolist"
                and m.meta.get("todoCard")
            ):
                existing_msg = m
                break

        if not existing_msg:
            return False

        todo_card = existing_msg.meta.get("todoCard", {})
        todo_card["ready_to_execute"] = data.get("ready_to_execute", False)
        flag_modified(existing_msg, "meta")
        db.commit()
        return True

    if event in ("todolist_task_added", "todolist_task_edited", "todolist_task_deleted"):
        # 原地更新最近一条 requirements_todolist message 中的 todolist
        all_msgs = message_service.get_messages_by_session(db, session_id)
        existing_msg = None
        for m in reversed(all_msgs):
            if (
                m.role == "assistant"
                and m.meta
                and m.meta.get("type") == "requirements_todolist"
                and m.meta.get("todoCard")
            ):
                existing_msg = m
                break

        if not existing_msg:
            return False

        todo_card = existing_msg.meta.get("todoCard", {})
        todolist = todo_card.get("todolist", [])

        if event == "todolist_task_added":
            todolist.append({
                "db_id": data.get("db_id"),
                "task_id": data.get("task_id"),
                "task": data.get("task_description"),
                "owner": data.get("owner"),
                "dispatch_tool": data.get("dispatch_tool"),
                "instruction": data.get("instruction"),
                "depends_on": [d.strip() for d in (data.get("depends_on") or "").split(",") if d.strip()],
                "done_criteria": data.get("done_criteria", ""),
                "status": "pending",
                "depth": 0,
                "parent_id": "",
                "agent_scope": "supervisor",
                "task_type": "",
                "sort_order": data.get("sort_order", len(todolist)),
            })

        elif event == "todolist_task_edited":
            target_id = data.get("db_id")
            for t in todolist:
                if t.get("db_id") == target_id:
                    t["task"] = data.get("task_description", t.get("task"))
                    t["owner"] = data.get("owner", t.get("owner"))
                    t["dispatch_tool"] = data.get("dispatch_tool", t.get("dispatch_tool"))
                    t["instruction"] = data.get("instruction", t.get("instruction"))
                    t["done_criteria"] = data.get("done_criteria", t.get("done_criteria"))
                    dep = data.get("depends_on")
                    if dep is not None:
                        t["depends_on"] = [d.strip() for d in dep.split(",") if d.strip()]
                    break

        elif event == "todolist_task_deleted":
            target_id = data.get("db_id")
            todolist[:] = [t for t in todolist if t.get("db_id") != target_id]

        flag_modified(existing_msg, "meta")
        db.commit()
        return True

    if event == "supervisor_runtime_event":
        message_service.create_message(
            db,
            session_id=session_id,
            role="assistant",
            content="",
            work_id=sess.work_id,
            sort_order=next_order,
            meta={
                "type": "supervisor_runtime_event",
                "run_id": data.get("run_id", ""),
                "event": data.get("event", ""),
                "payload": data.get("payload", {}),
            },
        )
        return True

    return False


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/start")
async def start_supervisor(
    payload: SupervisorStartRequest,
    current_user: User = Depends(get_current_user),
):
    """启动统筹 Agent 新会话。返回 SSE 流。"""
    t0 = time.perf_counter()
    gap_log("http_start", t0=t0, route="start", message_len=len(payload.message or ""), work_id=payload.work_id or "")
    logger.info("supervisor_router.start message_len=%s work_id=%s", len(payload.message or ""), payload.work_id)
    queue: asyncio.Queue = asyncio.Queue()

    async def event_generator():
        task = _launch_supervisor_task(
            queue=queue,
            runner=lambda agent: agent.start(
                message=payload.message,
                auto_mode=payload.auto_mode,
                enable_todolist=payload.enable_todolist,
                enable_evaluation=payload.enable_evaluation,
            ),
            work_id=payload.work_id,
            log_label="start",
            t0=t0,
            user_id=current_user.id,
        )

        try:
            first_yield = False
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                if not first_yield:
                    first_yield = True
                    sid = data.get("session_id") if isinstance(data, dict) else None
                    gap_log("first_sse_yield", session_id=sid, t0=t0, event=event)
                yield _sse_format(event, data)
        except asyncio.CancelledError:
            logger.info("supervisor_router.start client disconnected; run task continues in background")
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resume")
async def resume_supervisor(
    payload: SupervisorResumeRequest,
    current_user: User = Depends(get_current_user),
):
    """恢复已有统筹 Agent 会话。返回 SSE 流。"""
    t0 = time.perf_counter()
    gap_log(
        "http_start",
        session_id=payload.session_id,
        t0=t0,
        route="resume",
        message_len=len(payload.message or ""),
    )
    logger.info("supervisor_router.resume session_id=%s message_len=%s", payload.session_id, len(payload.message or ""))
    queue: asyncio.Queue = asyncio.Queue()

    async def event_generator():
        task = _launch_supervisor_task(
            queue=queue,
            runner=lambda agent: agent.resume(
                session_id=payload.session_id,
                message=payload.message,
                enable_todolist=payload.enable_todolist,
                enable_evaluation=payload.enable_evaluation,
            ),
            work_id=None,
            log_label="resume",
            t0=t0,
            session_id=payload.session_id,
            user_id=current_user.id,
        )

        try:
            first_yield = False
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                if not first_yield:
                    first_yield = True
                    gap_log(
                        "first_sse_yield",
                        session_id=payload.session_id,
                        t0=t0,
                        event=event,
                    )
                yield _sse_format(event, data)
        except asyncio.CancelledError:
            logger.info("supervisor_router.resume client disconnected; run task continues in background")
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/confirm")
def confirm_action(
    payload: SupervisorConfirmRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """确认或拒绝挂起的操作（章节编辑、大纲编辑、角色编辑）。"""
    from app.models.agent_model import SupervisorSession
    from app.services.supervisor.edit_chapter_agent import EditChapterAgent
    from app.services.supervisor.outline_agent import OutlineAgent

    session = db.query(SupervisorSession).filter_by(id=payload.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status != "waiting" or not session.active_child:
        raise HTTPException(status_code=400, detail="当前没有待确认的操作")

    child = session.active_child
    action_type = child.get("type")
    task_item_id = child.get("task_item_id")
    next_order = message_service.get_next_sort_order(db, session.id)

    # Helper: 更新关联 TaskItem 状态
    def _update_linked_task(new_status: str, result_summary: str = "", error_message: str = ""):
        if not task_item_id:
            return
        from app.models.task_item_model import TaskItem
        task = db.query(TaskItem).filter_by(id=task_item_id).first()
        if task and task.status == "in_progress":
            task.status = new_status
            if result_summary:
                task.result_summary = result_summary
            if error_message:
                task.error_message = error_message
            from datetime import datetime, timezone
            task.completed_at = datetime.now(timezone.utc)

    if action_type == "edit_chapter":
        work_id = child.get("work_id")
        chapter_number = child.get("chapter_number")
        new_content = payload.new_content or child.get("new_content", "")

        def emit(event, data):
            pass

        edit_agent = EditChapterAgent(emit=emit)

        if payload.action == "accept":
            result = edit_agent.accept_edit(
                work_id=work_id,
                chapter_number=chapter_number,
                new_content=new_content,
                db=db,
            )
            message_service.create_message(
                db, session_id=session.id, role="user",
                content="[接受修改]", work_id=work_id,
                sort_order=next_order, meta={"action": "accept"},
            )
            message_service.create_message(
                db, session_id=session.id, role="assistant",
                content=f"第{chapter_number}章修改已保存。", work_id=work_id,
                sort_order=next_order + 1,
                meta={"intent": "edit_chapter", "action": "accepted"},
            )
            session.status = "completed"
            session.stage = "done"
            session.active_child = None
            _update_linked_task("completed", f"第{chapter_number}章修改已保存")
            db.commit()
            return {"status": "accepted", "chapter_number": chapter_number}
        else:
            message_service.create_message(
                db, session_id=session.id, role="user",
                content="[拒绝修改]", work_id=work_id,
                sort_order=next_order, meta={"action": "reject"},
            )
            message_service.create_message(
                db, session_id=session.id, role="assistant",
                content=f"第{chapter_number}章修改已取消，正文保持不变。", work_id=work_id,
                sort_order=next_order + 1,
                meta={"intent": "edit_chapter", "action": "rejected"},
            )
            session.status = "completed"
            session.stage = "done"
            session.active_child = None
            _update_linked_task("failed", f"第{chapter_number}章修改被用户拒绝")
            db.commit()
            return {"status": "rejected", "chapter_number": chapter_number}

    elif action_type == "edit_outline":
        work_id = child.get("work_id")

        if payload.action == "accept":
            OutlineAgent.commit_outline_edit(work_id=work_id, db=db)
            message_service.create_message(
                db, session_id=session.id, role="user",
                content="[确认大纲修改]", work_id=work_id,
                sort_order=next_order, meta={"action": "accept"},
            )
            message_service.create_message(
                db, session_id=session.id, role="assistant",
                content="大纲修改已保存。", work_id=work_id,
                sort_order=next_order + 1,
                meta={"intent": "edit_outline", "action": "accepted"},
            )
            session.status = "completed"
            session.stage = "done"
            session.active_child = None
            _update_linked_task("completed", "大纲修改已保存")
            db.commit()
            return {"status": "accepted", "type": "edit_outline"}
        else:
            OutlineAgent.rollback_outline_edit(work_id=work_id, db=db)
            message_service.create_message(
                db, session_id=session.id, role="user",
                content="[拒绝大纲修改]", work_id=work_id,
                sort_order=next_order, meta={"action": "reject"},
            )
            message_service.create_message(
                db, session_id=session.id, role="assistant",
                content="大纲修改已取消，保持原样。", work_id=work_id,
                sort_order=next_order + 1,
                meta={"intent": "edit_outline", "action": "rejected"},
            )
            session.status = "completed"
            session.stage = "done"
            session.active_child = None
            _update_linked_task("failed", "大纲修改被用户拒绝")
            db.commit()
            return {"status": "rejected", "type": "edit_outline"}

    elif action_type == "requirements_planner":
        work_id = child.get("work_id")
        result = child.get("result", {}) or {}

        if payload.action == "accept":
            message_service.create_message(
                db, session_id=session.id, role="user",
                content="[确认需求与任务清单]", work_id=work_id,
                sort_order=next_order, meta={"action": "accept"},
            )
            message_service.create_message(
                db, session_id=session.id, role="assistant",
                content="需求与任务清单已确认，可按该计划继续执行。",
                work_id=work_id,
                sort_order=next_order + 1,
                meta={
                    "intent": "requirements_planner",
                    "action": "accepted",
                    "requirements_plan": result,
                },
            )
            session.status = "completed"
            session.stage = "done"
            session.active_child = None
            _update_linked_task("completed", "需求与任务清单已确认")
            db.commit()
            return {"status": "accepted", "type": "requirements_planner"}
        else:
            message_service.create_message(
                db, session_id=session.id, role="user",
                content="[拒绝需求与任务清单]", work_id=work_id,
                sort_order=next_order, meta={"action": "reject"},
            )
            message_service.create_message(
                db, session_id=session.id, role="assistant",
                content="需求与任务清单已取消，请提供新的目标或补充信息。",
                work_id=work_id,
                sort_order=next_order + 1,
                meta={"intent": "requirements_planner", "action": "rejected"},
            )
            session.status = "completed"
            session.stage = "done"
            session.active_child = None
            _update_linked_task("failed", "需求与任务清单被用户拒绝")
            db.commit()
            return {"status": "rejected", "type": "requirements_planner"}

    raise HTTPException(status_code=400, detail=f"不支持的操作类型: {action_type}")


@router.post("/interrupt")
def interrupt_session(
    payload: SupervisorInterruptRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """中断正在运行的 Supervisor 会话。Agent 将在当前 LLM/工具调用完成后停止。"""
    from app.models.agent_model import SupervisorSession

    session = db.query(SupervisorSession).filter_by(id=payload.session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status not in ("running",):
        raise HTTPException(status_code=400, detail="会话未在运行中，无法中断")

    session.interrupted = True
    db.commit()
    log_event(
        db,
        work_id=session.work_id or "",
        session_id=session.id,
        session_type="supervisor",
        role="system",
        content="用户请求中断",
        meta={"user_id": current_user.id},
    )
    return {"status": "ok", "detail": "中断请求已提交，Agent 将在当前步骤完成后停止"}


def _launch_supervisor_task(
    *,
    queue: asyncio.Queue,
    runner: Callable[[SupervisorAgent], Awaitable[dict]],
    work_id: str | None,
    log_label: str,
    t0: float,
    session_id: str | None = None,
    user_id: str | None = None,
) -> asyncio.Task:
    """启动独立后台任务，避免绑定到当前 HTTP 请求的 db 生命周期。"""

    current_session_id: str | None = session_id
    run_db: Session | None = None

    def emit(event: str, data: dict):
        nonlocal current_session_id, run_db
        gap_log_sse_emit(event, data, session_id=current_session_id, t0=t0)
        logger.debug(
            "supervisor_router.emit event=%s data_keys=%s",
            event,
            list(data.keys()) if isinstance(data, dict) else type(data),
        )
        if event == "session_created":
            current_session_id = data.get("session_id")
        if current_session_id and isinstance(data, dict):
            try:
                if event in PERSISTABLE_EVENTS:
                    persist_db = SessionLocal()
                    try:
                        persist_event_message(persist_db, current_session_id, event, data)
                    finally:
                        persist_db.close()
            except Exception:
                logger.exception("persist supervisor event failed: %s", event)
        queue.put_nowait((event, data))

    async def run():
        nonlocal run_db
        run_db = SessionLocal()
        gap_log("background_task_begin", session_id=current_session_id, t0=t0, log_label=log_label)
        agent = SupervisorAgent(
            emit=emit,
            db=run_db,
            work_id=work_id,
            user_id=user_id,
            gap_trace_t0=t0,
        )
        try:
            logger.info("supervisor_router.run begin agent.%s", log_label)
            await runner(agent)
            gap_log("background_task_end", session_id=current_session_id, t0=t0, log_label=log_label)
            logger.info(
                "supervisor_router.run end agent.%s elapsed_ms=%.1f",
                log_label,
                (time.perf_counter() - t0) * 1000,
            )
        except Exception as exc:
            logger.exception("supervisor_router.run agent.%s FAILED: %s", log_label, exc)
            emit("error", {"message": str(exc)})
        finally:
            if current_session_id and run_db is not None:
                try:
                    from app.services.session_service import delete_session_if_no_user_messages

                    delete_session_if_no_user_messages(run_db, current_session_id)
                except Exception:
                    logger.exception(
                        "supervisor_router cleanup orphan session failed session_id=%s",
                        current_session_id,
                    )
            run_db.close()
            run_db = None
            await queue.put(None)

    task = asyncio.create_task(run())
    _RUN_TASKS.add(task)
    task.add_done_callback(_RUN_TASKS.discard)
    return task
