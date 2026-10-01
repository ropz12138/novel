"""Supervisor 兼容端点 — 对齐 main 分支 API，使 useSupervisorChat 可直接复用"""
import json
import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from database import SessionLocal
from models.user import User
from models.work import CanvasWork
from routers.auth import get_current_user
from services.agents.supervisor import supervisor_agent
from services.agents.chapter_review_policy import ChapterReviewPolicy, current_chapter_review_policy
from services.chapter_review_preference import save_chapter_review_intensity
from services.canvas_checkpoint_service import capture_canvas_checkpoint, prepare_edit_resend
from services.session_store import session_store
from services.supervisor_event_persist import persist_supervisor_event_safe
from services.supervisor_stream_broker import supervisor_stream_broker
from services.supervisor_run_queue import supervisor_run_queue
from services import user_action_service as action_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/supervisor", tags=["supervisor"])
_background_supervisor_tasks = supervisor_run_queue.tasks


async def stop_supervisor_run(session_id: str) -> dict:
    """取消指定会话正在跑的 Supervisor 后台任务。"""
    stopped = await supervisor_run_queue.stop(session_id)
    return {"success": True, "stopped": stopped}


def _queue_state(session_id):
    return {
        "running": supervisor_run_queue.running(session_id),
        "pending_messages": [
            {"id": item["id"], "content": item["content"]}
            for item in supervisor_run_queue.pending(session_id)
        ],
    }


def _require_owned_work(work_id: Optional[str], user_id: str) -> None:
    """确保 Agent 只能绑定当前用户自己的作品。"""
    if not work_id:
        return
    db = SessionLocal()
    try:
        owned = db.query(CanvasWork.id).filter(
            CanvasWork.id == work_id,
            CanvasWork.user_id == user_id,
        ).first()
    finally:
        db.close()
    if not owned:
        raise HTTPException(status_code=404, detail="作品不存在")


class SupervisorStartRequest(BaseModel):
    message: str
    work_id: Optional[str] = None
    context_node_ids: Optional[List[str]] = None
    chapter_review_intensity: Literal["low", "medium", "high"] = "medium"


class SupervisorResumeRequest(BaseModel):
    session_id: str
    message: str
    context_node_ids: Optional[List[str]] = None
    chapter_review_intensity: Literal["low", "medium", "high"] = "medium"


class SupervisorEditResendRequest(BaseModel):
    session_id: str
    message_id: str
    message: str
    context_node_ids: Optional[List[str]] = None
    chapter_review_intensity: Literal["low", "medium", "high"] = "medium"


class SupervisorStreamResumeRequest(BaseModel):
    session_id: str


class SupervisorStopRequest(BaseModel):
    session_id: str


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _wrap_emit(session_id: str):
    """包装 emit：SSE 推送 + Todolist 持久化。"""

    async def emit(event: str, data: dict):
        if session_id and isinstance(data, dict):
            try:
                persist_supervisor_event_safe(session_id, event, data)
            except Exception:
                logger.exception("persist supervisor event failed: %s", event)
        await supervisor_stream_broker.publish(session_id, event, data)

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


def _store_user_actions_message(session_id: str, work_id: Optional[str]) -> Optional[dict]:
    """把"自上次 agent 回复后的用户画布操作"作为一条独立 user 消息存入对话，
    排在用户文字消息之前。agent 在本轮会同时看到操作与用户文字。"""
    if not work_id:
        return None
    db = SessionLocal()
    try:
        section = action_svc.build_pending_actions_section(db, work_id)
    except Exception:
        logger.exception("build user_actions_section failed work_id=%s", work_id)
        section = ""
    finally:
        db.close()
    if section:
        return session_store.add_message(
            session_id, "user", section, meta={"type": "user_canvas_actions"}
        )
    return None


async def _execute_supervisor_run(
    *,
    session_id: str,
    user_message: str,
    context: dict,
    wrapped_emit,
) -> None:
    review_policy_token = current_chapter_review_policy.set(
        ChapterReviewPolicy(context.get("chapter_review_intensity", "medium"))
    )
    try:
        result = await supervisor_agent.run(
            user_message,
            context,
            emit=wrapped_emit,
        )
        if not result.get("success", False):
            raise RuntimeError(result.get("error") or "Supervisor 执行失败")
        workflow_status = result.get("workflow_status")
        session_status = workflow_status if workflow_status in {"needs_user", "needs_revision"} else "completed"
        session_store.update_session(session_id, stage="done", status=session_status)
        _advance_watermark_from_context(context)
    except asyncio.CancelledError:
        session_store.mark_session_interrupted(session_id)
        _advance_watermark_from_context(context)
        try:
            await wrapped_emit("supervisor_interrupted", {"reason": "cancelled"})
        except Exception:
            logger.exception("emit supervisor_interrupted failed session_id=%s", session_id)
        raise
    except Exception as e:
        await wrapped_emit("error", {"message": str(e)})
        session_store.update_session(session_id, stage="done", status="error")
    finally:
        current_chapter_review_policy.reset(review_policy_token)


def _advance_watermark_from_context(context: dict) -> None:
    """agent 成功结束后推进水位线：下次对话只感知更新的用户操作。"""
    if not context:
        return
    work_id = context.get("work_id")
    run_started_at = context.get("run_started_at")
    if not work_id or not run_started_at:
        return
    db = SessionLocal()
    try:
        action_svc.advance_watermark(db, work_id, run_started_at)
    except Exception:
        logger.exception("advance canvas_action_watermark failed work_id=%s", work_id)
    finally:
        db.close()


def _stream_supervisor_run(
    *,
    session_id: str,
    user_message: str,
    work_id: Optional[str],
    user_id: str,
    context_node_ids: Optional[List[str]],
    chapter_review_intensity: Literal["low", "medium", "high"] = "medium",
    emit_session_created: bool = True,
    user_message_id: Optional[str] = None,
    user_actions_message: Optional[dict] = None,
    pre_run_events: Optional[list[tuple[str, dict]]] = None,
):
    db = SessionLocal()
    try:
        save_chapter_review_intensity(db, user_id, chapter_review_intensity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        db.close()
    if not supervisor_run_queue.running(session_id):
        supervisor_stream_broker.begin(session_id)

    async def run_agent(item):
        sid = item["session_id"]
        wrapped_emit = _wrap_emit(sid)
        terminal = None

        async def emit(event, data):
            nonlocal terminal
            if event in {"supervisor_done", "supervisor_interrupted", "error"}:
                terminal = (event, data)
            else:
                await wrapped_emit(event, data)

        msg_id = item["user_message_id"]
        if msg_id is None:
            msg = session_store.add_message(sid, "user", item["content"], work_id=item["work_id"])
            msg_id = msg["id"]
            _capture_checkpoint_before_agent(sid, item["work_id"], msg)
        session_store.update_session(sid, stage="running", status="running")
        await wrapped_emit("queue_updated", _queue_state(sid))
        await wrapped_emit("queued_message_started", {"message_id": msg_id, "content": item["content"]})
        context = {
            "user_id": item["user_id"],
            "work_id": item["work_id"],
            "session_id": sid,
            "context_node_ids": item["context_node_ids"],
            "chapter_review_intensity": item["intensity"],
            "run_started_at": datetime.utcnow(),
        }
        try:
            await _execute_supervisor_run(
                session_id=sid, user_message=item["content"], context=context, wrapped_emit=emit,
            )
        finally:
            more = bool(supervisor_run_queue.pending(sid))
            if more:
                session_store.update_session(sid, stage="running", status="running")
            if terminal:
                event, data = terminal
                if more:
                    event = "supervisor_turn_done" if event == "supervisor_done" else "supervisor_turn_error"
                await wrapped_emit(event, data)

    supervisor_run_queue.submit(session_id, {
        "id": str(uuid.uuid4()), "session_id": session_id, "content": user_message,
        "work_id": work_id, "user_id": user_id, "context_node_ids": context_node_ids,
        "intensity": chapter_review_intensity, "user_message_id": user_message_id,
    }, run_agent)

    async def event_generator():
        if emit_session_created:
            yield _sse_format("session_created", {"session_id": session_id})
        if user_actions_message:
            yield _sse_format("user_actions_message_stored", user_actions_message)
        if user_message_id:
            yield _sse_format("user_message_stored", {"message_id": user_message_id})
        if pre_run_events:
            for event, data in pre_run_events:
                yield _sse_format(event, data)
        yield _sse_format("queue_updated", _queue_state(session_id))
        async for event, data in supervisor_stream_broker.subscribe(
            session_id,
        ):
            if event != "session_created":
                yield _sse_format(event, data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/stream")
async def resume_supervisor_stream(
    payload: SupervisorStreamResumeRequest,
    user: User = Depends(get_current_user),
):
    """从客户端最后确认的数据块之后恢复当前 Supervisor 流。"""
    session = session_store.get_session(payload.session_id)
    if not session or session["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    if not supervisor_stream_broker.has_stream(payload.session_id):
        raise HTTPException(status_code=409, detail="当前会话没有可恢复的流")

    async def event_generator():
        yield _sse_format("queue_updated", _queue_state(payload.session_id))
        async for event, data in supervisor_stream_broker.subscribe(
            payload.session_id,
        ):
            yield _sse_format(event, data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/stop")
async def stop_supervisor(
    payload: SupervisorStopRequest,
    user: User = Depends(get_current_user),
):
    """主动中断当前 Supervisor 运行：已完成的入库，进行中的工具整笔丢弃。"""
    session = session_store.get_session(payload.session_id)
    if not session or session["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    _require_owned_work(session.get("work_id"), user.id)
    return await stop_supervisor_run(payload.session_id)


@router.post("/start")
async def start_supervisor(
    payload: SupervisorStartRequest,
    user: User = Depends(get_current_user),
):
    """启动 Supervisor 会话（SSE 流式）"""
    _require_owned_work(payload.work_id, user.id)
    session = session_store.create_session(user_id=user.id, work_id=payload.work_id)
    session_id = session["id"]

    # 新会话没有可供 Agent 延续理解的历史轮次，不注入此前积累的画布操作气泡。
    user_actions_message = None
    user_msg = session_store.add_message(session_id, "user", payload.message, work_id=payload.work_id)
    _capture_checkpoint_before_agent(session_id, payload.work_id, user_msg)

    return _stream_supervisor_run(
        session_id=session_id,
        user_message=payload.message,
        work_id=payload.work_id,
        user_id=user.id,
        context_node_ids=payload.context_node_ids,
        chapter_review_intensity=payload.chapter_review_intensity,
        user_message_id=user_msg["id"] if user_msg else None,
        user_actions_message=user_actions_message,
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
    _require_owned_work(session.get("work_id"), user.id)

    session_id = payload.session_id
    user_actions_message = None
    user_msg = None
    session_store.update_session(session_id, stage="running", status="running")

    return _stream_supervisor_run(
        session_id=session_id,
        user_message=payload.message,
        work_id=session.get("work_id"),
        user_id=user.id,
        context_node_ids=payload.context_node_ids,
        chapter_review_intensity=payload.chapter_review_intensity,
        emit_session_created=True,
        user_message_id=user_msg["id"] if user_msg else None,
        user_actions_message=user_actions_message,
    )


@router.post("/enqueue")
async def enqueue_supervisor(payload: SupervisorResumeRequest, user: User = Depends(get_current_user)):
    started_new_stream = not supervisor_run_queue.running(payload.session_id)
    await resume_supervisor(payload, user)
    state = _queue_state(payload.session_id)
    await supervisor_stream_broker.publish(payload.session_id, "queue_updated", state)
    return {**state, "started_new_stream": started_new_stream}


@router.get("/queue/{session_id}")
async def get_supervisor_queue(session_id: str, user: User = Depends(get_current_user)):
    session = session_store.get_session(session_id)
    if not session or session["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return _queue_state(session_id)


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
    if supervisor_run_queue.running(payload.session_id):
        raise HTTPException(status_code=409, detail="任务运行中，请等待队列完成后编辑历史消息")
    if not work_id:
        raise HTTPException(status_code=400, detail="会话未绑定作品，无法恢复画布")
    _require_owned_work(work_id, user.id)

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
        chapter_review_intensity=payload.chapter_review_intensity,
        emit_session_created=False,
        user_message_id=new_msg["id"],
        pre_run_events=[
            ("canvas_restored", {"message_id": payload.message_id}),
            ("messages_truncated", {"from_message_id": payload.message_id}),
            ("user_message_edited", {"message_id": new_msg["id"], "content": new_msg["content"]}),
        ],
    )
