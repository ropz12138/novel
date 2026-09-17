"""Supervisor 技能工作流的运行记录与版本化中间产物。"""
from datetime import datetime, timezone
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    work_id = Column(String(36), ForeignKey("canvas_works.id", ondelete="CASCADE"), nullable=True, index=True)
    chapter_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(String(36), ForeignKey("supervisor_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    skill_name = Column(String(100), nullable=False)
    status = Column(String(30), nullable=False, default="running")
    current_stage = Column(String(80), nullable=False, default="")
    revision_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class WorkflowArtifact(Base):
    __tablename__ = "workflow_artifacts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(36), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    work_id = Column(String(36), ForeignKey("canvas_works.id", ondelete="CASCADE"), nullable=True, index=True)
    chapter_node_id = Column(String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_artifact_id = Column(String(36), ForeignKey("workflow_artifacts.id", ondelete="SET NULL"), nullable=True)
    artifact_type = Column(String(80), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

