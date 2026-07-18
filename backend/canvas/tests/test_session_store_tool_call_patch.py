"""session_store tool_call success 回写测试。"""
import uuid

import pytest

from app.models.session import SupervisorMessage, SupervisorSession
from app.models.user import User
from app.services.session_store import session_store


def _setup(db):
    user = User(
        id=str(uuid.uuid4()),
        username=f"user_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex}@test.local",
        password_hash="hash",
    )
    db.add(user)
    db.flush()
    session = SupervisorSession(id=str(uuid.uuid4()), user_id=user.id)
    db.add(session)
    db.commit()
    return session.id


def test_patch_tool_call_success_by_call_id(db_session):
    session_id = _setup(db_session)
    session_store.add_message(
        session_id,
        role="tool_call",
        content="write_todolist",
        meta={"tool_call_id": "call_1", "success": True},
    )

    ok = session_store.patch_tool_call_success(
        session_id,
        call_id="call_1",
        tool_name="write_todolist",
        success=False,
    )
    assert ok is True

    msgs = db_session.query(SupervisorMessage).filter_by(session_id=session_id).all()
    assert msgs[0].meta["success"] is False


@pytest.fixture
def db_session(isolated_db):
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
