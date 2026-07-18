"""角色关系线 — 仅连接 character 节点之间的社会关系。"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class CharacterRelation(Base):
    __tablename__ = "character_relations"
    __table_args__ = (
        CheckConstraint("source_id <> target_id", name="ck_character_relation_no_self_loop"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    work_id = Column(
        String(36),
        ForeignKey("canvas_works.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_id = Column(
        String(36),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id = Column(
        String(36),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type = Column(String(100), nullable=False)
    label = Column(String(100), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    work = relationship("CanvasWork", back_populates="character_relations")
