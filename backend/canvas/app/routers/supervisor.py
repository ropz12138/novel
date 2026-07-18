"""Supervisor 兼容端点 — 对齐 main 分支 API，使 useSupervisorChat 可直接复用"""
import json
import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.database import SessionLocal
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.agents.supervisor import supervisor_agent
from app.services.canvas_checkpoint_service import capture_canvas_checkpoint, prepare_edit_resend
from app.services.session_store import session_store
from app.services.supervisor_event_persist import persist_supervisor_event_safe

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/supervisor", tags=["supervisor"])


class SupervisorStartRequest(BaseModel):
    message: str
    work_id: Optional[str] = None
    auto_mode: bool = True
    enable_todolist: bool = False
    enable_evaluation: bool = False
    context_node_ids: Optional[List[str]] = None


class SupervisorResumeRequest(BaseModel):
    session_id: str
    message: str
    enable_todolist: bool = False
    enable_evaluation: bool = False
    context_node_ids: Optional[List[str]] = None


class SupervisorEditResendRequest(BaseModel):
    session_id: str
    message_id: str
    message: str
    enable_todolist: bool = False
    enable_evaluation: bool = False
    context_node_ids: Optional[List[str]] = None


class SupervisorInterruptRequest(BaseModel):
    session_id: str


class SupervisorConfirmRequest(BaseModel):
    session_id: str
    action: str  # accept / reject
    new_content: Optional[str] = None


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _wrap_emit(session_id: str, queue_put):
    """包装 emit：SSE 推送 + Todolist 持久化。"""

    async def emit(event: str, data: dict):
        if session_id and isinstance(data, dict):
            try:
                persist_supervisor_event_safe(session_id, event, data)
            except Exception:
                logger.exception("persist supervisor event failed: %s", event)
        await queue_put((event, data))

    return emit


def _capture_checkpoint_before_agent(
    session_id: str,
    work_id: Optional[str],
    user_message: dict,
) -> None:
    if not work_id or not user_message:
        return
    db = SessionLocal()
    try:
        capture_canvas_checkpoint(
            db,
            session_id=session_id,
            work_id=work_id,
            trigger_message_id=user_message["id"],
            sort_order=user_message.get("sort_order", 0),
        )
    finally:
        db.close()


async def _execute_supervisor_run(
    *,
    session_id: str,
    user_message: str,
    context: dict,
    wrapped_emit,
) -> None:
    try:
        await supervisor_agent.run(user_message, context, emit=wrapped_emit)
        session_store.update_session(session_id, stage="done", status="completed")
    except asyncio.CancelledError:
        session_store.mark_session_interrupted(session_id)
        try:
            await wrapped_emit("supervisor_interrupted", {"reason": "cancelled"})
        except Exception:
            logger.exception("emit supervisor_interrupted failed session_id=%s", session_id)
        raise
    except Exception as e:
        await wrapped_emit("error", {"message": str(e)})
        session_store.update_session(session_id, stage="done", status="error")


def _stream_supervisor_run(
    *,
    session_id: str,
    user_message: str,
    work_id: Optional[str],
    user_id: str,
    context_node_ids: Optional[List[str]],
    emit_session_created: bool = True,
    user_message_id: Optional[str] = None,
    pre_run_events: Optional[list[tuple[str, dict]]] = None,
):
    queue: asyncio.Queue = asyncio.Queue()
    wrapped_emit = _wrap_emit(session_id, queue.put)

    async def run_agent():
        try:
            context = {
                "user_id": user_id,
                "work_id": work_id,
                "session_id": session_id,
                "context_node_ids": context_node_ids,
            }
            await _execute_supervisor_run(
                session_id=session_id,
                user_message=user_message,
                context=context,
                wrapped_emit=wrapped_emit,
            )
        finally:
            await queue.put(None)

    async def event_generator():
        if emit_session_created:
            yield _sse_format("session_created", {"session_id": session_id})
        if user_message_id:
            yield _sse_format("user_message_stored", {"message_id": user_message_id})
        if pre_run_events:
            for event, data in pre_run_events:
                yield _sse_format(event, data)
        task = asyncio.create_task(run_agent())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                if event == "session_created":
                    continue
                yield _sse_format(event, data)
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
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


@router.post("/start")
async def start_supervisor(
    payload: SupervisorStartRequest,
    user: User = Depends(get_current_user),
):
    """启动 Supervisor 会话（SSE 流式）"""
    session = session_store.create_session(user_id=user.id, work_id=payload.work_id)
    session_id = session["id"]

    user_msg = session_store.add_message(session_id, "user", payload.message, work_id=payload.work_id)
    _capture_checkpoint_before_agent(session_id, payload.work_id, user_msg)

    return _stream_supervisor_run(
        session_id=session_id,
        user_message=payload.message,
        work_id=payload.work_id,
        user_id=user.id,
        context_node_ids=payload.context_node_ids,
        user_message_id=user_msg["id"] if user_msg else None,
    )


@router.post("/resume")
async def resume_supervisor(
    payload: SupervisorResumeRequest,
    user: User = Depends(get_current_user),
):
    """恢复 Supervisor 会话（SSE 流式）"""
    session = session_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")

    session_id = payload.session_id
    user_msg = session_store.add_message(
        session_id, "user", payload.message, work_id=session.get("work_id"),
    )
    session_store.update_session(session_id, stage="running", status="running")
    _capture_checkpoint_before_agent(session_id, session.get("work_id"), user_msg)

    return _stream_supervisor_run(
        session_id=session_id,
        user_message=payload.message,
        work_id=session.get("work_id"),
        user_id=user.id,
        context_node_ids=payload.context_node_ids,
        emit_session_created=True,
        user_message_id=user_msg["id"] if user_msg else None,
    )


@router.post("/edit-resend")
async def edit_resend_supervisor(
    payload: SupervisorEditResendRequest,
    user: User = Depends(get_current_user),
):
    """编辑已发送用户消息并重新发送：先恢复画布到该消息执行前，截断对话尾巴，再跑 Agent。"""
    session = session_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")

    work_id = session.get("work_id")
    if not work_id:
        raise HTTPException(status_code=400, detail="会话未绑定作品，无法恢复画布")

    db = SessionLocal()
    try:
        new_msg = prepare_edit_resend(
            db,
            session_id=payload.session_id,
            work_id=work_id,
            message_id=payload.message_id,
            new_content=payload.message,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        db.close()

    session_store.update_session(payload.session_id, stage="running", status="running")

    return _stream_supervisor_run(
        session_id=payload.session_id,
        user_message=payload.message,
        work_id=work_id,
        user_id=user.id,
        context_node_ids=payload.context_node_ids,
        emit_session_created=False,
        pre_run_events=[
            ("canvas_restored", {"message_id": payload.message_id}),
            ("messages_truncated", {"from_message_id": payload.message_id}),
            ("user_message_edited", {"message_id": new_msg["id"], "content": new_msg["content"]}),
        ],
    )


@router.post("/interrupt")
async def interrupt_supervisor(
    payload: SupervisorInterruptRequest,
    user: User = Depends(get_current_user),
):
    """中断 Supervisor 会话 — canvas 暂不支持，返回 OK"""
    return {"status": "ok", "detail": "canvas 后端暂不支持中断"}


@router.post("/confirm")
async def confirm_action(
    payload: SupervisorConfirmRequest,
    user: User = Depends(get_current_user),
):
    """确认操作 — canvas 暂不支持，返回 OK"""
    return {"status": "accepted"}
