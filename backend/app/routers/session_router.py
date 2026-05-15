"""Session router — API endpoints for supervisor session management."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.controllers import session_controller
from app.schemas.message_schema import MessageOut

router = APIRouter(tags=["chat-sessions"])


@router.get("/supervisor-sessions")
def list_supervisor_sessions_api(
    work_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return session_controller.list_sessions(work_id, db)


@router.get("/supervisor-sessions/{session_id}/messages", response_model=list[MessageOut])
def get_supervisor_session_messages_api(
    session_id: str,
    db: Session = Depends(get_db),
):
    return session_controller.get_session_messages(session_id, db)


@router.delete("/supervisor-sessions/{session_id}", status_code=204)
def delete_supervisor_session_api(
    session_id: str,
    db: Session = Depends(get_db),
):
    session_controller.delete_session(session_id, db)
