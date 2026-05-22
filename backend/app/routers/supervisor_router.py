"""Supervisor SSE router — 统一 Agent 入口"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.schemas.supervisor_schema import SupervisorStartRequest, SupervisorResumeRequest, SupervisorConfirmRequest
from app.services.supervisor.supervisor_agent import SupervisorAgent
from app.services.agent_log_service import log_event, new_session_id
from app.services import message_service

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
        text = (
            f"章节评估完成：编辑 {editor.get('total_score', '-')} /60，"
            f"读者 {reader.get('total_score', '-')} /60"
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
                    "foreshadows": data.get("foreshadows", []),
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
                    "foreshadows": data.get("foreshadows", []),
                },
            },
        )
        return True

    return False


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/start")
async def start_supervisor(
    payload: SupervisorStartRequest,
):
    """启动统筹 Agent 新会话。返回 SSE 流。"""
    t0 = time.perf_counter()
    logger.info("supervisor_router.start message_len=%s work_id=%s", len(payload.message or ""), payload.work_id)
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: str, data: dict):
        logger.debug("supervisor_router.emit event=%s data_keys=%s", event, list(data.keys()) if isinstance(data, dict) else type(data))
        queue.put_nowait((event, data))

    async def event_generator():
        task = _launch_supervisor_task(
            queue=queue,
            runner=lambda agent: agent.start(message=payload.message, auto_mode=payload.auto_mode),
            work_id=payload.work_id,
            log_label="start",
            t0=t0,
        )

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
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
):
    """恢复已有统筹 Agent 会话。返回 SSE 流。"""
    t0 = time.perf_counter()
    logger.info("supervisor_router.resume session_id=%s message_len=%s", payload.session_id, len(payload.message or ""))
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: str, data: dict):
        logger.debug("supervisor_router.emit event=%s data_keys=%s", event, list(data.keys()) if isinstance(data, dict) else type(data))
        queue.put_nowait((event, data))

    async def event_generator():
        task = _launch_supervisor_task(
            queue=queue,
            runner=lambda agent: agent.resume(session_id=payload.session_id, message=payload.message),
            work_id=None,
            log_label="resume",
            t0=t0,
            session_id=payload.session_id,
        )

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
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


@router.get("/{session_id}/status")
def get_supervisor_status(
    session_id: str,
    db: Session = Depends(get_db),
):
    """查询统筹 Agent 会话状态。"""
    from app.models.agent_model import SupervisorSession
    session = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not session:
        return {"status": "not_found"}
    msg_count = message_service.get_next_sort_order(db, session_id)
    return {
        "id": session.id,
        "work_id": session.work_id,
        "stage": session.stage,
        "status": session.status,
        "message_count": msg_count,
    }


@router.post("/confirm")
def confirm_action(
    payload: SupervisorConfirmRequest,
    db: Session = Depends(get_db),
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
    next_order = message_service.get_next_sort_order(db, session.id)

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
            db.commit()
            return {"status": "rejected", "type": "requirements_planner"}

    raise HTTPException(status_code=400, detail=f"不支持的操作类型: {action_type}")


def _launch_supervisor_task(
    *,
    queue: asyncio.Queue,
    runner: Callable[[SupervisorAgent], Awaitable[dict]],
    work_id: str | None,
    log_label: str,
    t0: float,
    session_id: str | None = None,
) -> asyncio.Task:
    """启动独立后台任务，避免绑定到当前 HTTP 请求的 db 生命周期。"""

    current_session_id: str | None = session_id
    run_db: Session | None = None

    def emit(event: str, data: dict):
        nonlocal current_session_id, run_db
        logger.debug(
            "supervisor_router.emit event=%s data_keys=%s",
            event,
            list(data.keys()) if isinstance(data, dict) else type(data),
        )
        if event == "session_created":
            current_session_id = data.get("session_id")
        if current_session_id and run_db is not None and isinstance(data, dict):
            try:
                if event in PERSISTABLE_EVENTS:
                    persist_event_message(run_db, current_session_id, event, data)
            except Exception:
                logger.exception("persist supervisor event failed: %s", event)
        queue.put_nowait((event, data))

    async def run():
        nonlocal run_db
        run_db = SessionLocal()
        agent = SupervisorAgent(emit=emit, db=run_db, work_id=work_id)
        try:
            logger.info("supervisor_router.run begin agent.%s", log_label)
            await runner(agent)
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
