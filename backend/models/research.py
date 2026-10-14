"""独立小说研究 Agent 的任务、文本版本、事件与产出。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ResearchJob(Base):
    __tablename__ = "research_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename = Column(String(500), nullable=False)
    status = Column(String(30), nullable=False, default="queued", index=True)
    stage = Column(String(100), nullable=False, default="准备文件")
    active_version_id = Column(
        String(36),
        ForeignKey(
            "research_text_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_research_jobs_active_version",
        ),
        nullable=True,
    )
    working_memory = Column(Text, nullable=False, default="")
    progress_current = Column(Integer, nullable=False, default=0)
    progress_total = Column(Integer, nullable=False, default=0)
    progress_unit = Column(String(30), nullable=False, default="步骤")
    progress_detail = Column(Text, nullable=False, default="")
    error = Column(Text, nullable=False, default="")
    completed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    versions = relationship(
        "ResearchTextVersion",
        back_populates="job",
        cascade="all, delete-orphan",
        foreign_keys="ResearchTextVersion.job_id",
    )
    events = relationship(
        "ResearchEvent",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ResearchEvent.sequence",
    )
    artifacts = relationship(
        "ResearchArtifact",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ResearchArtifact.created_at",
    )
    instructions = relationship(
        "ResearchInstruction",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ResearchInstruction.sequence",
    )


class ResearchTextVersion(Base):
    __tablename__ = "research_text_versions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(
        String(36),
        ForeignKey("research_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_version_id = Column(
        String(36),
        ForeignKey("research_text_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_number = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False, default="cleaned")
    encoding = Column(String(50), nullable=False, default="utf-8")
    file_path = Column(Text, nullable=False)
    index_path = Column(Text, nullable=True)
    sha256 = Column(String(64), nullable=False)
    manifest_text = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    job = relationship(
        "ResearchJob",
        back_populates="versions",
        foreign_keys=[job_id],
    )


class ResearchEvent(Base):
    __tablename__ = "research_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(
        String(36),
        ForeignKey("research_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence = Column(Integer, nullable=False, default=0)
    event_type = Column(String(30), nullable=False)
    content = Column(Text, nullable=False, default="")
    meta_text = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    job = relationship("ResearchJob", back_populates="events")


class ResearchArtifact(Base):
    __tablename__ = "research_artifacts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(
        String(36),
        ForeignKey("research_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_type = Column(String(40), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False, default="")
    metadata_text = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    job = relationship("ResearchJob", back_populates="artifacts")


class ResearchInstruction(Base):
    __tablename__ = "research_instructions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(
        String(36),
        ForeignKey("research_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=False)
    consumed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    job = relationship("ResearchJob", back_populates="instructions")


class ResearchSession(Base):
    """独立研究对话；作品通过消息引用，不在会话上绑定。"""

    __tablename__ = "research_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title = Column(String(200), nullable=False, default="新对话")
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    messages = relationship(
        "ResearchMessage", back_populates="session", cascade="all, delete-orphan",
        order_by="ResearchMessage.sequence",
    )


class ResearchMessage(Base):
    __tablename__ = "research_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(
        String(36), ForeignKey("research_sessions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False, default="")
    sequence = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    session = relationship("ResearchSession", back_populates="messages")
    work_references = relationship(
        "ResearchMessageWorkReference", back_populates="message",
        cascade="all, delete-orphan",
    )
    chapter_reference = relationship(
        "ResearchMessageChapterReference", back_populates="message",
        cascade="all, delete-orphan", uselist=False,
    )


class ResearchMessageWorkReference(Base):
    __tablename__ = "research_message_work_references"

    message_id = Column(
        String(36), ForeignKey("research_messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    work_id = Column(
        String(36), ForeignKey("research_jobs.id", ondelete="CASCADE"),
        primary_key=True, index=True,
    )

    message = relationship("ResearchMessage", back_populates="work_references")
    work = relationship("ResearchJob")


class ResearchMessageChapterReference(Base):
    __tablename__ = "research_message_chapter_references"

    message_id = Column(
        String(36), ForeignKey("research_messages.id", ondelete="CASCADE"),
        primary_key=True,
    )
    version_id = Column(
        String(36), ForeignKey("research_text_versions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    section_index = Column(Integer, nullable=False)

    message = relationship("ResearchMessage", back_populates="chapter_reference")
    version = relationship("ResearchTextVersion")
