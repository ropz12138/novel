from sqlalchemy import Column, String, Text, DateTime, JSON, ForeignKey
from datetime import datetime
import uuid

from app.database import Base


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    work_id = Column(String(36), ForeignKey("canvas_works.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), default="")
    content = Column(Text, default="")
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    summary = Column(Text, default="")
    outline_binding_id = Column(String(36), nullable=True)
    node_id = Column(String(36), ForeignKey("nodes.id", ondelete="SET NULL"), nullable=True, index=True)
    new_facts = Column(JSON, default=list)
    foreshadows = Column(JSON, default=list)
    generation_context = Column(JSON, default=dict)
