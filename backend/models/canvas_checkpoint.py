"""画布 checkpoint — 每条用户消息触发 Agent 前的画布快照。"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Float, DateTime, ForeignKey, Integer, JSON
from sqlalchemy.orm import relationship

from database import Base


class CanvasCheckpoint(Base):
    __tablename__ = "canvas_checkpoints"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(
        String(36),
        ForeignKey("supervisor_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    work_id = Column(
        String(36),
        ForeignKey("canvas_works.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trigger_message_id = Column(
        String(36),
        ForeignKey("supervisor_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    sort_order = Column(Integer, nullable=False, default=0)
    node_count = Column(Integer, nullable=False, default=0)
    edge_count = Column(Integer, nullable=False, default=0)
    relation_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    nodes = relationship(
        "CanvasCheckpointNode",
        back_populates="checkpoint",
        cascade="all, delete-orphan",
    )
    edges = relationship(
        "CanvasCheckpointEdge",
        back_populates="checkpoint",
        cascade="all, delete-orphan",
    )
    character_relations = relationship(
        "CanvasCheckpointRelation",
        back_populates="checkpoint",
        cascade="all, delete-orphan",
    )


class CanvasCheckpointNode(Base):
    __tablename__ = "canvas_checkpoint_nodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checkpoint_id = Column(
        String(36),
        ForeignKey("canvas_checkpoints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id = Column(String(36), nullable=False)
    type = Column(String(30), nullable=False)
    layer = Column(Integer, nullable=False, default=0)
    sort_order = Column(Integer, nullable=False, default=0)
    scope = Column(String(20), nullable=False, default="local")
    title = Column(String(200), nullable=False)
    content = Column(Text, default="")
    extra_data = Column(JSON, default=dict)
    position_x = Column(Float, default=0.0)
    position_y = Column(Float, default=0.0)

    checkpoint = relationship("CanvasCheckpoint", back_populates="nodes")


class CanvasCheckpointEdge(Base):
    __tablename__ = "canvas_checkpoint_edges"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checkpoint_id = Column(
        String(36),
        ForeignKey("canvas_checkpoints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    edge_id = Column(String(36), nullable=False)
    source_id = Column(String(36), nullable=False)
    target_id = Column(String(36), nullable=False)
    edge_type = Column(String(100), nullable=False, default="uses")
    label = Column(String(200), default="")
    extra_data = Column(JSON, default=dict)

    checkpoint = relationship("CanvasCheckpoint", back_populates="edges")


class CanvasCheckpointRelation(Base):
    __tablename__ = "canvas_checkpoint_relations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    checkpoint_id = Column(
        String(36),
        ForeignKey("canvas_checkpoints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_id = Column(String(36), nullable=False)
    source_id = Column(String(36), nullable=False)
    target_id = Column(String(36), nullable=False)
    relation_type = Column(String(100), nullable=False)
    label = Column(String(100), default="")

    checkpoint = relationship("CanvasCheckpoint", back_populates="character_relations")
