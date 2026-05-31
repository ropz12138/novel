import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    works: Mapped[list["Work"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Work(Base):
    __tablename__ = "works"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="未命名作品")
    genre: Mapped[str] = mapped_column(String(60), nullable=False, default="未分类")
    idea: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    outline_tree: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="草稿")
    requirements_doc: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user: Mapped["User"] = relationship(back_populates="works")
    chapters: Mapped[list["Chapter"]] = relationship(back_populates="work", cascade="all, delete-orphan")
    characters: Mapped[list["Character"]] = relationship(back_populates="work", cascade="all, delete-orphan")


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("work_id", "chapter_number", name="uq_work_chapter"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    work_id: Mapped[str] = mapped_column(String(36), ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="生成中")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    work: Mapped["Work"] = relationship(back_populates="chapters")


class Character(Base):
    __tablename__ = "characters"
    __table_args__ = (
        UniqueConstraint("work_id", "name", name="uq_work_char_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    work_id: Mapped[str] = mapped_column(String(36), ForeignKey("works.id", ondelete="CASCADE"), nullable=False)

    # ── 基础设定（框架层） ──
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    role_type: Mapped[str] = mapped_column(String(100), nullable=False, default="配角")
    gender: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    age: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    appearance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    background: Mapped[str] = mapped_column(Text, nullable=False, default="")
    skills: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── 动态状态（正文反馈更新） ──
    current_status: Mapped[str] = mapped_column(Text, nullable=False, default="存活")
    current_goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_location: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    last_chapter: Mapped[int] = mapped_column(Integer, nullable=True)
    relationships: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # ── 元数据 ──
    first_chapter: Mapped[int] = mapped_column(Integer, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    work: Mapped["Work"] = relationship(back_populates="characters")


class AgentLog(Base):
    """Records every message/event in agent conversations for debugging and review."""
    __tablename__ = "agent_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    work_id: Mapped[str] = mapped_column(String(36), ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # session_type: outline_chat / agent_writing / chapter_chat
    session_type: Mapped[str] = mapped_column(String(30), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=True)
    # role: user / assistant / system / tool / event
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Extra metadata: stage, event type, tool calls, etc.
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ChapterMetadata(Base):
    """LLM 生成的章节元数据 — 正文写作/编辑后自动产出"""
    __tablename__ = "chapter_metadata"
    __table_args__ = (
        UniqueConstraint("work_id", "chapter_number", name="uq_work_chapter_metadata"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    work_id: Mapped[str] = mapped_column(String(36), ForeignKey("works.id", ondelete="CASCADE"), nullable=False)
    chapter_number: Mapped[int] = mapped_column(Integer, nullable=False)

    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_plot_points: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    outline_links: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    involved_characters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    foreshadows: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    facts: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
