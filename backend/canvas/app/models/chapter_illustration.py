from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from datetime import datetime
import uuid

from app.database import Base


class ChapterIllustration(Base):
    __tablename__ = "chapter_illustrations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    work_id = Column(String(36), ForeignKey("canvas_works.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(Text, nullable=False)
    prompt = Column(Text, nullable=False)
    insert_after_paragraph = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
