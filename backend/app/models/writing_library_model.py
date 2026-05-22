"""Global shared writing-technique library models."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.work_model import _utcnow, _uuid


class WritingSource(Base):
    __tablename__ = "writing_sources"

    source_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_site: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    source_url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    genre_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    heat_metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    credibility_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class TechniqueCard(Base):
    __tablename__ = "technique_cards"

    technique_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    problem_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    genre_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    applicable_stages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    trigger_conditions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    execution_template: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    anti_patterns: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    risk_notes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    constraints_supported: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    novelty_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    stability_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class TechniqueEvidence(Base):
    __tablename__ = "technique_evidence"

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    technique_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("technique_cards.technique_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("writing_sources.source_id", ondelete="SET NULL"),
        nullable=True,
    )
    chapter_ref: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    signal_type: Mapped[str] = mapped_column(String(40), nullable=False, default="structure")
    signal_value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    excerpt_digest: Mapped[str] = mapped_column(Text, nullable=False, default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class RetrievalFeedback(Base):
    __tablename__ = "retrieval_feedback"

    log_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    technique_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("technique_cards.technique_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query_fingerprint: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    feedback_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
