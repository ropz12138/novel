"""session_store tool_call success 回写测试。"""
import uuid

import pytest

from models.session import SupervisorMessage, SupervisorSession
from models.user import User
from services.session_store import session_store


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


def test_session_context_tokens_use_latest_request_not_total(db_session):
    sid = _setup(db_session)
    user_id = session_store.get_session(sid)["user_id"]
    empty = session_store.create_session(user_id)
    foreign_sid = _setup(db_session)
    for target, tokens in [(sid, 9000), (sid, 1200), (foreign_sid, 88000)]:
        session_store.add_message(target, role="tool_call", content="read_node_content",
                                  meta={"usage_metadata": {"input_tokens": tokens, "output_tokens": 100}})
    session_store.add_message(sid, role="tool_result", content="正文")
    sessions = {s["id"]: s for s in session_store.list_sessions(user_id)}
    assert sessions[sid]["context_input_tokens"] == 1200
    assert sessions[empty["id"]]["context_input_tokens"] is None
    assert foreign_sid not in sessions
    assert session_store.get_session(sid)["context_input_tokens"] == 1200


@pytest.fixture
def db_session(isolated_db):
    from database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
