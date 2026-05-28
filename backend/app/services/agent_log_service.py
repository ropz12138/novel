"""AgentLog service — write and query agent conversation logs."""

import uuid
from sqlalchemy.orm import Session

from app.models.work_model import AgentLog


def log_event(
    db: Session,
    *,
    work_id: str,
    session_id: str,
    session_type: str,
    role: str,
    content: str,
    chapter_number: int | None = None,
    meta: dict | None = None,
) -> AgentLog:
    """Write a single log entry. Commits immediately."""
    entry = AgentLog(
        work_id=work_id,
        session_id=session_id,
        session_type=session_type,
        chapter_number=chapter_number,
        role=role,
        content=content,
        meta=meta or {},
    )
    db.add(entry)
    db.commit()
    return entry


def new_session_id() -> str:
    return str(uuid.uuid4())
