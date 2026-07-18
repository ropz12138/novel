"""TodoItem 模型 — Supervisor 会话的自然语言任务清单"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class TodoItem(Base):
    __tablename__ = "todo_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(
        String(36),
        ForeignKey("supervisor_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(String(20), nullable=False)
    task = Column(Text, nullable=False, default="")
    status = Column(String(20), nullable=False, default="pending")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    session = relationship("SupervisorSession", backref="todo_items")
