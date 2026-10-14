"""Session 存储 — 使用 PostgreSQL 持久化"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models.session import SupervisorSession, SupervisorMessage


class SessionStore:
    """PostgreSQL Session 存储"""

    def __init__(self):
        self._db_factory = None

    def _get_db(self):
        if self._db_factory:
            return self._db_factory()
        from database import SessionLocal
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
            result = self._session_to_dict(session)
            result["context_input_tokens"] = self._context_inputs(db, [session_id]).get(session_id)
            return result
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
            inputs = self._context_inputs(db, [s.id for s in sessions])
            return [{**self._session_to_dict(s), "context_input_tokens": inputs.get(s.id)} for s in sessions]
        finally:
            db.close()

    @staticmethod
    def _context_inputs(db, session_ids: list[str]) -> dict:
        """批量读取每个会话最近一次已记录的输入用量，不加载正文或累计用量。"""
        if not session_ids:
            return {}
        tokens = SupervisorMessage.meta["usage_metadata"]["input_tokens"].as_integer()
        rows = (db.query(SupervisorMessage.session_id, tokens)
                .filter(SupervisorMessage.session_id.in_(session_ids), tokens.isnot(None))
                .distinct(SupervisorMessage.session_id)
                .order_by(SupervisorMessage.session_id, SupervisorMessage.sort_order.desc(),
                          SupervisorMessage.created_at.desc(), SupervisorMessage.id.desc()).all())
        return dict(rows)

    def mark_session_interrupted(self, session_id: str) -> bool:
        """将会话标记为 interrupted（仅当 status=running 时生效）。"""
        db = self._get_db()
        try:
            session = db.query(SupervisorSession).filter(SupervisorSession.id == session_id).first()
            if not session or session.status != "running":
                return False
            session.status = "interrupted"
            session.stage = "done"
            session.updated_at = datetime.now(timezone.utc)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    def recover_stale_running_sessions(self) -> int:
        """将仍为 running 的会话标记为 interrupted（进程崩溃后的僵尸 session）。"""
        db = self._get_db()
        try:
            rows = db.query(SupervisorSession).filter(SupervisorSession.status == "running").all()
            if not rows:
                return 0
            now = datetime.now(timezone.utc)
            for session in rows:
                session.status = "interrupted"
                session.stage = "done"
                session.updated_at = now
            db.commit()
            return len(rows)
        except Exception as e:
            db.rollback()
            raise e
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

    def add_message(self, session_id: str, role: str, content: str, meta: Optional[dict] = None, work_id: Optional[str] = None, *, before_message_id: str | None = None) -> Optional[dict]:
        """添加消息"""
        db = self._get_db()
        try:
            # 获取当前最大 sort_order
            max_order = db.query(SupervisorMessage.sort_order).filter(
                SupervisorMessage.session_id == session_id
            ).order_by(SupervisorMessage.sort_order.desc()).first()
            next_order = (max_order[0] + 1) if max_order else 0
            if before_message_id is not None:
                anchor = db.query(SupervisorMessage).filter_by(
                    id=before_message_id, session_id=session_id,
                ).with_for_update().one()
                next_order = anchor.sort_order
                db.query(SupervisorMessage).filter(
                    SupervisorMessage.session_id == session_id,
                    SupervisorMessage.sort_order >= next_order,
                ).update({SupervisorMessage.sort_order: SupervisorMessage.sort_order + 1}, synchronize_session=False)

            message = SupervisorMessage(
                session_id=session_id,
                role=role,
                content=content,
                work_id=work_id,
                sort_order=next_order,
                meta=meta or {},
            )
            db.add(message)

            # 更新会话标题（用第一条用户消息；跳过系统注入的操作摘要消息）
            session = db.query(SupervisorSession).filter(SupervisorSession.id == session_id).first()
            if (
                session
                and session.title == "新对话"
                and role == "user"
                and (meta or {}).get("type") != "user_canvas_actions"
            ):
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
        """获取会话消息（Todolist 从 todo_items 同步最新状态）"""
        db = self._get_db()
        try:
            messages = db.query(SupervisorMessage).filter(
                SupervisorMessage.session_id == session_id
            ).order_by(SupervisorMessage.sort_order).all()
            result = [self._message_to_dict(m) for m in messages]
            from services.supervisor_event_persist import enrich_messages_with_todolist
            return enrich_messages_with_todolist(db, session_id, result)
        finally:
            db.close()

    def latest_usage_metadata(self, session_id: str) -> Optional[dict]:
        """读取最近一次持久化的 LLM usage 元数据。"""
        db = self._get_db()
        try:
            rows = (
                db.query(SupervisorMessage)
                .filter(SupervisorMessage.session_id == session_id)
                .order_by(SupervisorMessage.sort_order.desc())
                .all()
            )
            for row in rows:
                meta = row.meta or {}
                if isinstance(meta, dict) and meta.get("usage_metadata"):
                    return meta.get("usage_metadata")
            return None
        finally:
            db.close()

    def patch_tool_call_success(
        self,
        session_id: str,
        *,
        call_id: str = "",
        tool_name: str = "",
        success: bool = True,
    ) -> bool:
        """更新最近一次匹配的 tool_call 成功状态。"""
        from sqlalchemy.orm.attributes import flag_modified

        db = self._get_db()
        try:
            rows = (
                db.query(SupervisorMessage)
                .filter_by(session_id=session_id, role="tool_call")
                .order_by(SupervisorMessage.sort_order.desc())
                .all()
            )
            for row in rows:
                meta = dict(row.meta or {})
                if call_id and meta.get("tool_call_id") == call_id:
                    meta["success"] = success
                    row.meta = meta
                    flag_modified(row, "meta")
                    db.commit()
                    return True
            for row in rows:
                if tool_name and row.content == tool_name:
                    meta = dict(row.meta or {})
                    meta["success"] = success
                    row.meta = meta
                    flag_modified(row, "meta")
                    db.commit()
                    return True
            return False
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()

    def discard_unpaired_tool_calls(self, session_id: str) -> None:
        """删除没有对应 tool_result 的 tool_call，避免中断后历史消息对不齐。"""
        db = self._get_db()
        try:
            messages = (
                db.query(SupervisorMessage)
                .filter_by(session_id=session_id)
                .order_by(SupervisorMessage.sort_order)
                .all()
            )
            result_ids = {
                (message.meta or {}).get("tool_call_id")
                for message in messages
                if message.role == "tool_result" and (message.meta or {}).get("tool_call_id")
            }
            for message in messages:
                if message.role == "model_assistant":
                    payload = json.loads(message.content)
                    calls = payload.get("tool_calls", [])
                    completed = [call for call in calls if call["id"] in result_ids]
                    if len(completed) != len(calls):
                        payload["tool_calls"] = completed
                        if not completed and not payload["content"] and not payload.get("additional_kwargs"):
                            db.delete(message)
                        else:
                            message.content = json.dumps(payload, ensure_ascii=False)
                    continue
                if message.role != "tool_call":
                    continue
                call_id = (message.meta or {}).get("tool_call_id")
                if not call_id or call_id not in result_ids:
                    db.delete(message)
            db.commit()
        except Exception as e:
            db.rollback()
            raise e
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
            "sort_order": message.sort_order,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }


# 全局单例
session_store = SessionStore()
