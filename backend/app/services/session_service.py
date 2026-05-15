"""Session service — CRUD for supervisor sessions, queries messages from message_service."""
import logging

from sqlalchemy.orm import Session

from app.models.agent_model import SupervisorSession
from app.models.work_model import _uuid
from app.services import message_service

logger = logging.getLogger(__name__)


# ── Supervisor session ──

def create_session(
    db: Session,
    *,
    work_id: str | None = None,
    session_id: str | None = None,
) -> SupervisorSession:
    """Create a new supervisor session (SupervisorSession row only)."""
    session = SupervisorSession(
        id=session_id or _uuid(),
        work_id=work_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    logger.info("session_service.create id=%s work_id=%s", session.id, work_id)
    return session


def list_sessions(
    db: Session,
    work_id: str | None = None,
) -> list[SupervisorSession]:
    """List supervisor sessions, optionally filtered by work_id."""
    q = db.query(SupervisorSession)
    if work_id:
        q = q.filter_by(work_id=work_id)
    return q.order_by(SupervisorSession.updated_at.desc()).all()


def get_session(db: Session, session_id: str) -> SupervisorSession | None:
    return db.query(SupervisorSession).filter_by(id=session_id).first()


def delete_session(db: Session, session_id: str) -> bool:
    session = get_session(db, session_id)
    if not session:
        return False
    # 级联删除关联的 messages（由 FK ON DELETE CASCADE 保证）
    db.delete(session)
    db.commit()
    logger.info("session_service.delete id=%s", session_id)
    return True


def get_session_title(db: Session, session_id: str) -> str:
    """Dynamic title from the first user message."""
    return message_service.get_session_title(db, session_id)


def get_session_messages(db: Session, session_id: str) -> list[dict]:
    """Retrieve messages for a session from the messages table."""
    msgs = message_service.get_messages_by_session(db, session_id)
    return [
        {
            "id": m.id,
            "session_id": m.session_id,
            "work_id": m.work_id,
            "role": m.role,
            "content": m.content,
            "meta": m.meta,
            "sort_order": m.sort_order,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in msgs
    ]


# ── Outline chat compatibility ──
# outline_chat 路径不再使用 ChatSession 表，改用 no-op 桩函数保持兼容

def touch_session(db: Session, session_id: str) -> None:
    """No-op: previously bumped ChatSession.updated_at."""
    pass
