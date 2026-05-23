"""Session router — API endpoints for supervisor session management."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.controllers import session_controller
from app.models.work_model import User
from app.schemas.message_schema import MessageOut

router = APIRouter(tags=["chat-sessions"])


@router.get("/supervisor-sessions")
def list_supervisor_sessions_api(
    work_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_controller.list_sessions(work_id, db, user_id=current_user.id)


@router.get("/supervisor-sessions/{session_id}/messages", response_model=list[MessageOut])
def get_supervisor_session_messages_api(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return session_controller.get_session_messages(session_id, db, user_id=current_user.id)


@router.delete("/supervisor-sessions/{session_id}", status_code=204)
def delete_supervisor_session_api(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session_controller.delete_session(session_id, db, user_id=current_user.id)
