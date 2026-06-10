"""Session router — API endpoints for supervisor session management."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.controllers import session_controller
from app.models.work_model import User
from app.schemas.message_schema import MessageOut
from app.schemas.rpc_schema import OkResponse, SessionIdRpcRequest, SupervisorSessionsListRpcRequest

router = APIRouter(tags=["chat-sessions"])


@router.post("/supervisor-sessions/list")
def list_supervisor_sessions_api(
    payload: SupervisorSessionsListRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_controller.list_sessions(payload.work_id, db, user_id=current_user.id)


@router.post("/supervisor-sessions/messages", response_model=list[MessageOut])
def get_supervisor_session_messages_api(
    payload: SessionIdRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_controller.get_session_messages(payload.session_id, db, user_id=current_user.id)


@router.post("/supervisor-sessions/delete", response_model=OkResponse)
def delete_supervisor_session_api(
    payload: SessionIdRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_controller.delete_session(payload.session_id, db, user_id=current_user.id)
    return OkResponse()
