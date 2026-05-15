"""AgentLog controller — thin proxy to AgentLogService."""

from sqlalchemy.orm import Session

from app.services.agent_log_service import get_session_logs, list_sessions


def list_agent_sessions(
    work_id: str,
    db: Session,
    session_type: str | None = None,
    chapter_number: int | None = None,
) -> list[dict]:
    return list_sessions(db, work_id, session_type, chapter_number)


def get_agent_session_logs(session_id: str, db: Session) -> list[dict]:
    return get_session_logs(db, session_id)
