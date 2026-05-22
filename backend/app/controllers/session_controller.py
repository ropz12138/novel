"""Session controller — thin wrapper over session_service."""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services import session_service


def list_sessions(work_id: str | None, db: Session):
    sessions = session_service.list_sessions(db, work_id=work_id)
    return [_session_to_out(s, db) for s in sessions]


def get_session_messages(session_id: str, db: Session):
    s = session_service.get_session(db, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_service.get_session_messages(db, session_id)


def delete_session(session_id: str, db: Session):
    if not session_service.delete_session(db, session_id):
        raise HTTPException(status_code=404, detail="Session not found")


def _session_to_out(session, db) -> dict:
    """Convert SupervisorSession to API output dict, with dynamic title."""
    title = session_service.get_session_title(db, session.id)
    return {
        "id": session.id,
        "work_id": session.work_id,
        "type": "supervisor",
        "title": title,
        "stage": session.stage,
        "status": session.status,
        "auto_mode": session.auto_mode or False,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }
