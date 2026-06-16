import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, Float, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base


class Node(Base):
    __tablename__ = "nodes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    work_id = Column(String(36), ForeignKey("canvas_works.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(30), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, default="")
    extra_data = Column(JSON, default=dict)
    position_x = Column(Float, default=0.0)
    position_y = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    work = relationship("CanvasWork", back_populates="nodes")
