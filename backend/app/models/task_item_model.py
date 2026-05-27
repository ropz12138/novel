"""TaskItem 模型 — Supervisor 会话的任务清单状态机"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskItem(Base):
    __tablename__ = "task_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("supervisor_sessions.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(String(20), nullable=False)
    task_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner: Mapped[str] = mapped_column(String(50), nullable=False, default="supervisor")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    depends_on: Mapped[str] = mapped_column(Text, nullable=False, default="")
    done_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("task_items.id", ondelete="CASCADE"), nullable=True
    )
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agent_scope: Mapped[str] = mapped_column(String(50), nullable=False, default="supervisor")
    task_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    dispatch_tool: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def __init__(self, **kwargs):
        kwargs.setdefault("task_description", "")
        kwargs.setdefault("owner", "supervisor")
        kwargs.setdefault("status", "pending")
        kwargs.setdefault("depends_on", "")
        kwargs.setdefault("done_criteria", "")
        kwargs.setdefault("result_summary", "")
        kwargs.setdefault("sort_order", 0)
        kwargs.setdefault("parent_id", None)
        kwargs.setdefault("depth", 0)
        kwargs.setdefault("agent_scope", "supervisor")
        kwargs.setdefault("task_type", "")
        kwargs.setdefault("dispatch_tool", "")
        kwargs.setdefault("instruction", "")
        kwargs.setdefault("error_message", "")
        super().__init__(**kwargs)
