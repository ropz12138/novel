import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Float, DateTime, JSON, ForeignKey, Integer, Boolean
from sqlalchemy.orm import relationship
from database import Base


class Node(Base):
    __tablename__ = "nodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    work_id = Column(String(36), ForeignKey("canvas_works.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(30), nullable=False, index=True)
    layer = Column(Integer, nullable=False, default=0)
    scope = Column(String(20), nullable=False, default="local")
    title = Column(String(200), nullable=False)
    content = Column(Text, default="")
    extra_data = Column(JSON, default=dict)
    position_x = Column(Float, default=0.0)
    position_y = Column(Float, default=0.0)
    locked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    work = relationship("CanvasWork", back_populates="nodes")
