"""Canvas作品模型"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class CanvasWork(Base):
    """Canvas画布作品"""
    __tablename__ = "canvas_works"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False, default="未命名作品")
    description = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    nodes = relationship("Node", back_populates="work", cascade="all, delete-orphan")
    edges = relationship("Edge", back_populates="work", cascade="all, delete-orphan")
    character_relations = relationship(
        "CharacterRelation",
        back_populates="work",
        cascade="all, delete-orphan",
    )
