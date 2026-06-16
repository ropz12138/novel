"""Session 存储 — 使用 PostgreSQL 持久化"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.session import SupervisorSession, SupervisorMessage


class SessionStore:
    """PostgreSQL Session 存储"""

    def __init__(self):
        self._db_factory = None

    def _get_db(self):
        if self._db_factory:
            return self._db_factory()
        from app.database import SessionLocal
        return SessionLocal()

    def create_session(self, user_id: str, work_id: Optional[str] = None, **kwargs) -> dict:
        """创建新会话"""
        db = self._get_db()
        try:
            session = SupervisorSession(
                user_id=user_id,
                work_id=work_id,
                title=kwargs.get("title", "新对话"),
                stage=kwargs.get("stage", "running"),
                status=kwargs.get("status", "running"),
                auto_mode=kwargs.get("auto_mode", True),
                enable_todolist=kwargs.get("enable_todolist", False),
                enable_evaluation=kwargs.get("enable_evaluation", False),
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            return self._session_to_dict(session)
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话"""
        db = self._get_db()
        try:
            session = db.query(SupervisorSession).filter(SupervisorSession.id == session_id).first()
            if not session:
                return None
            return self._session_to_dict(session)
        finally:
            db.close()

    def list_sessions(self, user_id: str, work_id: Optional[str] = None) -> list[dict]:
        """列出用户会话"""
        db = self._get_db()
        try:
            query = db.query(SupervisorSession).filter(SupervisorSession.user_id == user_id)
            if work_id:
                query = query.filter(SupervisorSession.work_id == work_id)
            sessions = query.order_by(SupervisorSession.updated_at.desc()).all()
            return [self._session_to_dict(s) for s in sessions]
        finally:
            db.close()

    def update_session(self, session_id: str, **kwargs) -> Optional[dict]:
        """更新会话"""
        db = self._get_db()
        try:
            session = db.query(SupervisorSession).filter(SupervisorSession.id == session_id).first()
            if not session:
                return None
            for key, value in kwargs.items():
                if hasattr(session, key):
                    setattr(session, key, value)
            session.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(session)
            return self._session_to_dict(session)
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    def delete_session(self, session_id: str) -> bool:
        """删除会话"""
        db = self._get_db()
        try:
            session = db.query(SupervisorSession).filter(SupervisorSession.id == session_id).first()
            if not session:
                return False
            db.delete(session)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    def add_message(self, session_id: str, role: str, content: str, meta: Optional[dict] = None, work_id: Optional[str] = None) -> Optional[dict]:
        """添加消息"""
        db = self._get_db()
        try:
            # 获取当前最大 sort_order
            max_order = db.query(SupervisorMessage.sort_order).filter(
                SupervisorMessage.session_id == session_id
            ).order_by(SupervisorMessage.sort_order.desc()).first()
            next_order = (max_order[0] + 1) if max_order else 0

            message = SupervisorMessage(
                session_id=session_id,
                role=role,
                content=content,
                work_id=work_id,
                sort_order=next_order,
                meta=meta or {},
            )
            db.add(message)

            # 更新会话标题（用第一条用户消息）
            session = db.query(SupervisorSession).filter(SupervisorSession.id == session_id).first()
            if session and session.title == "新对话" and role == "user":
                session.title = content[:50] + ("..." if len(content) > 50 else "")
                session.updated_at = datetime.now(timezone.utc)

            db.commit()
            db.refresh(message)
            return self._message_to_dict(message)
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    def get_messages(self, session_id: str) -> list[dict]:
        """获取会话消息"""
        db = self._get_db()
        try:
            messages = db.query(SupervisorMessage).filter(
                SupervisorMessage.session_id == session_id
            ).order_by(SupervisorMessage.sort_order).all()
            return [self._message_to_dict(m) for m in messages]
        finally:
            db.close()

    def _session_to_dict(self, session: SupervisorSession) -> dict:
        """Session 对象转字典"""
        return {
            "id": session.id,
            "user_id": session.user_id,
            "work_id": session.work_id,
            "type": "supervisor",
            "title": session.title,
            "stage": session.stage,
            "status": session.status,
            "auto_mode": session.auto_mode,
            "enable_todolist": session.enable_todolist,
            "enable_evaluation": session.enable_evaluation,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        }

    def _message_to_dict(self, message: SupervisorMessage) -> dict:
        """Message 对象转字典"""
        return {
            "id": message.id,
            "session_id": message.session_id,
            "role": message.role,
            "content": message.content,
            "meta": message.meta or {},
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }


# 全局单例
session_store = SessionStore()
