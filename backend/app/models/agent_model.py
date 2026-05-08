from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.work_model import _uuid, _utcnow


class AgentState(Base):
    __tablename__ = "agent_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    work_id: Mapped[str] = mapped_column(String(36), ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Current execution stage: idle / thinking / query / write / outline_edit / done
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    # Execution status: running / waiting / completed / error
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")

    # Accumulated data from agent nodes
    user_instruction: Mapped[str] = mapped_column(Text, nullable=False, default="")
    thinking_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_pack: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chapter_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    chapter_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    outline_proposal: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # LangGraph checkpoint: serialized graph state for resume
    graph_checkpoint: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
