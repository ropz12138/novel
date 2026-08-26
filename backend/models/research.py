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
    UniqueConstraint,
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
    context_epochs = relationship(
        "ResearchContextEpoch",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="ResearchContextEpoch.epoch_number",
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


class ResearchContextEpoch(Base):
    """一次已提交的上下文压缩。

    structured_pack_text 是下一代上下文的入口；archive_path 指向不可变的
    完整请求归档。只有 status=active 的最新记录会被注入 Agent 快照。
    """

    __tablename__ = "research_context_epochs"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "epoch_number",
            name="uq_research_context_epoch_number",
        ),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(
        String(36),
        ForeignKey("research_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    epoch_number = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="active", index=True)
    source_event_start = Column(Integer, nullable=False, default=1)
    compact_through_sequence = Column(Integer, nullable=False)
    archive_path = Column(Text, nullable=False)
    archive_sha256 = Column(String(64), nullable=False)
    structured_pack_text = Column(Text, nullable=False)
    rendered_context_chars = Column(Integer, nullable=False, default=0)
    estimated_input_tokens = Column(Integer, nullable=False, default=0)
    model_name = Column(String(200), nullable=False, default="")
    schema_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    job = relationship("ResearchJob", back_populates="context_epochs")
