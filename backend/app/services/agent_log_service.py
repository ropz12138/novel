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


def list_sessions(db: Session, work_id: str, session_type: str | None = None, chapter_number: int | None = None) -> list[dict]:
    """List distinct sessions with summary info."""
    q = db.query(AgentLog).filter_by(work_id=work_id)
    if session_type:
        q = q.filter_by(session_type=session_type)
    if chapter_number is not None:
        q = q.filter_by(chapter_number=chapter_number)

    rows = q.order_by(AgentLog.created_at.desc()).all()

    # Group by session_id, keep first and last message per session
    sessions: dict[str, list[AgentLog]] = {}
    for row in rows:
        sessions.setdefault(row.session_id, []).append(row)

    result = []
    for sid, entries in sessions.items():
        entries.sort(key=lambda e: e.created_at)
        first = entries[0]
        last = entries[-1]
        user_msgs = [e for e in entries if e.role == "user"]
        result.append({
            "session_id": sid,
            "session_type": first.session_type,
            "chapter_number": first.chapter_number,
            "message_count": len(entries),
            "user_message_count": len(user_msgs),
            "first_message": user_msgs[0].content[:100] if user_msgs else "",
            "started_at": first.created_at.isoformat() if first.created_at else None,
            "last_activity": last.created_at.isoformat() if last.created_at else None,
        })

    result.sort(key=lambda s: s["last_activity"] or "", reverse=True)
    return result


def get_session_logs(db: Session, session_id: str) -> list[dict]:
    """Get all logs for a specific session, ordered by time."""
    rows = (
        db.query(AgentLog)
        .filter_by(session_id=session_id)
        .order_by(AgentLog.created_at)
        .all()
    )
    return [
        {
            "id": r.id,
            "role": r.role,
            "content": r.content,
            "meta": r.meta,
            "chapter_number": r.chapter_number,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
