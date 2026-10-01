"""Supervisor Sessions 兼容端点 — 对齐 main 分支 API"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from models.user import User
from routers.auth import get_current_user
from services.session_history_page import HISTORY_PAGE_VISIBLE_LIMIT
from services.session_store import session_store

router = APIRouter(prefix="/supervisor-sessions", tags=["supervisor-sessions"])


class SupervisorSessionsListRpcRequest(BaseModel):
    work_id: Optional[str] = None


class SessionIdRpcRequest(BaseModel):
    session_id: str


class SessionMessagesRpcRequest(BaseModel):
    session_id: str
    before_sort_order: Optional[int] = None
    limit: int = HISTORY_PAGE_VISIBLE_LIMIT


class SessionDiffRpcRequest(BaseModel):
    session_id: str
    message_id: str


@router.post("/list")
def list_supervisor_sessions(
    payload: SupervisorSessionsListRpcRequest,
    user: User = Depends(get_current_user),
):
    """列出用户会话"""
    return session_store.list_sessions(user_id=user.id, work_id=payload.work_id)


def _owned_session(session_id: str, user: User) -> dict:
    session = session_store.get_session(session_id)
    if not session or session["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/messages")
def get_supervisor_session_messages(
    payload: SessionMessagesRpcRequest,
    user: User = Depends(get_current_user),
):
    """分页返回聊天可见历史。默认取末尾 40 条。"""
    from services.session_history_page import list_history_page

    _owned_session(payload.session_id, user)
    return list_history_page(
        payload.session_id,
        before_sort_order=payload.before_sort_order,
        limit=payload.limit,
    )


@router.post("/messages/diff")
def get_supervisor_session_diff(
    payload: SessionDiffRpcRequest,
    user: User = Depends(get_current_user),
):
    """展开一条 diff 卡片时返回 hunks。"""
    from services.session_history_page import get_diff_hunks

    _owned_session(payload.session_id, user)
    detail = get_diff_hunks(payload.session_id, payload.message_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Diff not found")
    return detail


@router.post("/get")
def get_supervisor_session(
    payload: SessionIdRpcRequest,
    user: User = Depends(get_current_user),
):
    """获取单个会话的权威执行状态。"""
    session = session_store.get_session(payload.session_id)
    if not session or session["user_id"] != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


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
