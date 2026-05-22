"""Message service — CRUD for the messages table."""

import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.message_model import Message

logger = logging.getLogger(__name__)


def create_message(
    db: Session,
    *,
    session_id: str,
    role: str,
    content: str,
    meta: dict | None = None,
    sort_order: int | None = None,
    work_id: str | None = None,
    commit: bool = True,
) -> Message:
    """Insert one message row."""
    if sort_order is None:
        sort_order = get_next_sort_order(db, session_id)
    msg = Message(
        session_id=session_id,
        work_id=work_id,
        role=role,
        content=content,
        meta=meta or {},
        sort_order=sort_order,
    )
    db.add(msg)
    if commit:
        db.commit()
        db.refresh(msg)
    else:
        db.flush()
    return msg


def get_messages_by_session(db: Session, session_id: str) -> list[Message]:
    """Return all messages for a session, ordered by sort_order."""
    return (
        db.query(Message)
        .filter_by(session_id=session_id)
        .order_by(Message.sort_order, Message.created_at)
        .all()
    )


def get_messages_page_by_session(
    db: Session,
    session_id: str,
    *,
    limit: int = 100,
    before_sort_order: int | None = None,
) -> tuple[list[Message], bool]:
    """Return one page of messages for a session (newest-first window, final output oldest-first)."""
    safe_limit = max(1, min(limit, 500))
    q = db.query(Message).filter_by(session_id=session_id)
    if before_sort_order is not None:
        q = q.filter(Message.sort_order < before_sort_order)

    rows = (
        q.order_by(Message.sort_order.desc(), Message.created_at.desc())
        .limit(safe_limit + 1)
        .all()
    )
    has_more = len(rows) > safe_limit
    page = rows[:safe_limit]
    page.reverse()
    return page, has_more


def get_next_sort_order(db: Session, session_id: str) -> int:
    """Return the next sort_order value."""
    current_max = (
        db.query(func.max(Message.sort_order))
        .filter_by(session_id=session_id)
        .scalar()
    )
    if current_max is None:
        return 0
    return int(current_max) + 1


def get_session_title(db: Session, session_id: str) -> str:
    """Dynamic title: first user message, truncated to 50 chars."""
    msg = (
        db.query(Message)
        .filter_by(session_id=session_id, role="user")
        .order_by(Message.sort_order)
        .first()
    )
    if not msg or not msg.content:
        return "新对话"
    text = msg.content.replace("\n", " ")
    if len(text) > 50:
        return text[:50] + "..."
    return text


def delete_messages_by_session(db: Session, session_id: str) -> None:
    """Delete all messages belonging to a session."""
    msgs = get_messages_by_session(db, session_id)
    for m in msgs:
        db.delete(m)
    db.commit()
