"""Supervisor Sessions 兼容端点 — 对齐 main 分支 API"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.models.user import User
from app.routers.auth import get_current_user
from app.services.session_store import session_store

router = APIRouter(prefix="/supervisor-sessions", tags=["supervisor-sessions"])


class SupervisorSessionsListRpcRequest(BaseModel):
    work_id: Optional[str] = None


class SessionIdRpcRequest(BaseModel):
    session_id: str


@router.post("/list")
def list_supervisor_sessions(
    payload: SupervisorSessionsListRpcRequest,
    user: User = Depends(get_current_user),
):
    """列出用户会话"""
    return session_store.list_sessions(user_id=user.id, work_id=payload.work_id)


@router.post("/messages")
def get_supervisor_session_messages(
    payload: SessionIdRpcRequest,
    user: User = Depends(get_current_user),
):
    """获取会话消息"""
    session = session_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_store.get_messages(payload.session_id)


@router.post("/delete")
def delete_supervisor_session(
    payload: SessionIdRpcRequest,
    user: User = Depends(get_current_user),
):
    """删除会话"""
    session = session_store.get_session(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    session_store.delete_session(payload.session_id)
    return {"status": "ok"}
