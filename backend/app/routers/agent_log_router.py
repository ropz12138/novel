"""AgentLog router — API endpoints for viewing agent conversation logs."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.controllers.agent_log_controller import (
    get_agent_session_logs,
    list_agent_sessions,
)
from app.models.work_model import User

router = APIRouter(prefix="/works/{work_id}/logs", tags=["agent-logs"])


@router.get("")
def list_sessions_api(
    work_id: str,
    session_type: str | None = Query(None),
    chapter_number: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_agent_sessions(work_id, db, session_type, chapter_number, user_id=current_user.id)


@router.get("/{session_id}")
def get_session_logs_api(
    work_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_agent_session_logs(session_id, db, user_id=current_user.id)
