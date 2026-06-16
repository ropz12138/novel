"""Supervisor 兼容端点 — 对齐 main 分支 API，使 useSupervisorChat 可直接复用"""
import json
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.user import User
from app.routers.auth import get_current_user
from app.services.agents.supervisor import supervisor_agent
from app.services.session_store import session_store

router = APIRouter(prefix="/supervisor", tags=["supervisor"])


class SupervisorStartRequest(BaseModel):
    message: str
    work_id: Optional[str] = None
    auto_mode: bool = True
    enable_todolist: bool = False
    enable_evaluation: bool = False


class SupervisorResumeRequest(BaseModel):
    session_id: str
    message: str
    enable_todolist: bool = False
    enable_evaluation: bool = False


class SupervisorInterruptRequest(BaseModel):
    session_id: str


class SupervisorConfirmRequest(BaseModel):
    session_id: str
    action: str  # accept / reject
    new_content: Optional[str] = None


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/start")
async def start_supervisor(
    payload: SupervisorStartRequest,
    user: User = Depends(get_current_user),
):
    """启动 Supervisor 会话（SSE 流式）"""
    # 创建会话
    session = session_store.create_session(user_id=user.id, work_id=payload.work_id)
    session_id = session["id"]

    # 存储用户消息
    session_store.add_message(session_id, "user", payload.message)

    queue: asyncio.Queue = asyncio.Queue()
    assistant_content = ""

    async def emit(event: str, data: dict):
        nonlocal assistant_content
        # 捕获最终回复
        if event == "supervisor_done":
            assistant_content = data.get("message", "")
        await queue.put((event, data))

    async def run_agent():
        nonlocal assistant_content
        try:
            context = {
                "user_id": user.id,
                "work_id": payload.work_id,
                "session_id": session_id,
            }
            result = await supervisor_agent.run(payload.message, context, emit=emit)
            # 存储助手回复
            if assistant_content:
                session_store.add_message(session_id, "assistant", assistant_content)
            session_store.update_session(session_id, stage="done", status="completed")
        except Exception as e:
            await emit("error", {"message": str(e)})
            session_store.update_session(session_id, stage="done", status="error")
        finally:
            await queue.put(None)

    async def event_generator():
        # 先发送 session_created
        yield _sse_format("session_created", {"session_id": session_id})
        task = asyncio.create_task(run_agent())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                # 跳过 supervisor_agent 内部发送的 session_created（已在外层发送）
                if event == "session_created":
                    continue
                yield _sse_format(event, data)
        except asyncio.CancelledError:
            task.cancel()
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
    user: User = Depends(get_current_user),
):
    """恢复 Supervisor 会话（SSE 流式）"""
    session = session_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    session_id = payload.session_id

    # 存储用户消息
    session_store.add_message(session_id, "user", payload.message)
    session_store.update_session(session_id, stage="running", status="running")

    queue: asyncio.Queue = asyncio.Queue()
    assistant_content = ""

    async def emit(event: str, data: dict):
        nonlocal assistant_content
        if event == "supervisor_done":
            assistant_content = data.get("message", "")
        await queue.put((event, data))

    async def run_agent():
        nonlocal assistant_content
        try:
            context = {
                "user_id": user.id,
                "work_id": session.get("work_id"),
                "session_id": session_id,
            }
            result = await supervisor_agent.run(payload.message, context, emit=emit)
            if assistant_content:
                session_store.add_message(session_id, "assistant", assistant_content)
            session_store.update_session(session_id, stage="done", status="completed")
        except Exception as e:
            await emit("error", {"message": str(e)})
            session_store.update_session(session_id, stage="done", status="error")
        finally:
            await queue.put(None)

    async def event_generator():
        yield _sse_format("session_created", {"session_id": session_id})
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
            task.cancel()
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
