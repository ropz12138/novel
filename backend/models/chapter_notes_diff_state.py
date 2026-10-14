"""跨会话保存尚未确认的章节笔记修改基线。"""
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text

from database import Base


class ChapterNotesDiffState(Base):
    __tablename__ = "chapter_notes_diff_states"

    node_id = Column(String(36), ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)
    work_id = Column(String(36), ForeignKey("canvas_works.id", ondelete="CASCADE"), nullable=False, index=True)
    baseline_notes = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
