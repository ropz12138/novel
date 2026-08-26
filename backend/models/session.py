"""Session 模型 — Supervisor 会话和消息"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship
from database import Base


class SupervisorSession(Base):
    """Supervisor 会话"""
    __tablename__ = "supervisor_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    work_id = Column(String(36), ForeignKey("canvas_works.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(200), default="新对话")
    stage = Column(String(20), default="running")
    status = Column(String(20), default="running")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    messages = relationship("SupervisorMessage", back_populates="session", cascade="all, delete-orphan", order_by="SupervisorMessage.sort_order")


class SupervisorMessage(Base):
    """Supervisor 会话消息"""
    __tablename__ = "supervisor_messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("supervisor_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, tool_call, tool_result
    content = Column(Text, default="")
    work_id = Column(String(36), nullable=True)
    sort_order = Column(Integer, default=0)
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    # 关联
    session = relationship("SupervisorSession", back_populates="messages")
