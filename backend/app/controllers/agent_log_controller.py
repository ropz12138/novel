"""AgentLog controller — thin proxy to AgentLogService."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.work_model import Work
from app.services.agent_log_service import get_session_logs, list_sessions


def _verify_work_ownership(work_id: str, user_id: str, db: Session) -> None:
    work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")


def list_agent_sessions(
    work_id: str,
    db: Session,
    session_type: str | None = None,
    chapter_number: int | None = None,
    *,
    user_id: str,
) -> list[dict]:
    _verify_work_ownership(work_id, user_id, db)
    return list_sessions(db, work_id, session_type, chapter_number)


def get_agent_session_logs(session_id: str, db: Session, *, user_id: str) -> list[dict]:
    return get_session_logs(db, session_id)
