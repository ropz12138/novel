"""用户画布操作日志模型"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from database import Base


class UserCanvasAction(Base):
    """用户在画布上的手动操作日志。

    仅记录来自 REST API 的用户操作；agent 通过工具直接操作 DB，不经过 REST，
    因此天然不会出现在此日志中——这是区分"用户行为"与"agent 行为"的依据。
    """
    __tablename__ = "user_canvas_actions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    work_id = Column(String(36), ForeignKey("canvas_works.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type = Column(String(30), nullable=False, index=True)
    target_id = Column(String(36), nullable=False, index=True)
    target_type = Column(String(30), nullable=False, default="")
    target_title = Column(String(200), nullable=False, default="")
    content_preview = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    work = relationship("CanvasWork", back_populates="user_canvas_actions")
