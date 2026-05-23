"""Agent models — AgentState for chapter agent, SupervisorSession for supervisor agent"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
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


class SupervisorSession(Base):
    """统筹 Agent 的会话状态"""
    __tablename__ = "supervisor_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # 关联作品（可为空，创建大纲后绑定）
    work_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("works.id", ondelete="SET NULL"), nullable=True)

    # 执行阶段: idle / routing / executing / done
    stage: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    # 执行状态: running / waiting / completed / error
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")

    # 自动模式：True 时所有编辑操作直接执行，不等待用户确认（默认开启）
    auto_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 当前执行中的子 Agent 会话信息
    active_child: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
