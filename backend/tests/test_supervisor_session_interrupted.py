"""Supervisor 会话中断与僵尸 session 恢复 — TDD。"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from main import app
import database
from models.session import SupervisorSession
from routers.auth import get_current_user
from models.user import User
from services.session_store import session_store


client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="owner", email="owner@t.t", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def test_mark_session_interrupted_only_when_running(db_session):
    session = session_store.create_session(user_id=db_session.query(User).first().id)
    assert session["status"] == "running"

    changed = session_store.mark_session_interrupted(session["id"])
    assert changed is True

    updated = session_store.get_session(session["id"])
    assert updated["status"] == "interrupted"
    assert updated["stage"] == "done"

    changed_again = session_store.mark_session_interrupted(session["id"])
    assert changed_again is False
    assert session_store.get_session(session["id"])["status"] == "interrupted"


def test_mark_session_interrupted_no_op_for_completed(db_session):
    user_id = db_session.query(User).first().id
    session = session_store.create_session(user_id=user_id)
    session_store.update_session(session["id"], stage="done", status="completed")

    assert session_store.mark_session_interrupted(session["id"]) is False
    assert session_store.get_session(session["id"])["status"] == "completed"


def test_recover_stale_running_sessions(db_session):
    user_id = db_session.query(User).first().id
    s1 = session_store.create_session(user_id=user_id, title="僵尸1")
    s2 = session_store.create_session(user_id=user_id, title="僵尸2")
    session_store.update_session(s2["id"], stage="done", status="completed")

    count = session_store.recover_stale_running_sessions()
    assert count == 1
    assert session_store.get_session(s1["id"])["status"] == "interrupted"
    assert session_store.get_session(s2["id"])["status"] == "completed"


def test_startup_recovers_stale_running_sessions(db_session, monkeypatch):
    user_id = db_session.query(User).first().id
    session_store.create_session(user_id=user_id, title="启动前僵尸")

    import main as main_module

    main_module.on_startup()

    sessions = db_session.query(SupervisorSession).filter_by(title="启动前僵尸").all()
    assert len(sessions) == 1
    assert sessions[0].status == "interrupted"


def test_execute_supervisor_run_marks_interrupted_on_cancel(db_session, monkeypatch):
    user_id = db_session.query(User).first().id
    session = session_store.create_session(user_id=user_id)
    emitted = []

    async def cancelled_run(*args, **kwargs):
        raise asyncio.CancelledError()

    async def capture_emit(event, data):
        emitted.append((event, data))

    monkeypatch.setattr(
        "routers.supervisor.supervisor_agent.run",
        cancelled_run,
    )

    from routers.supervisor import _execute_supervisor_run

    async def _run():
        with pytest.raises(asyncio.CancelledError):
            await _execute_supervisor_run(
                session_id=session["id"],
                user_message="hello",
                context={"session_id": session["id"]},
                wrapped_emit=capture_emit,
            )

    asyncio.run(_run())

    updated = session_store.get_session(session["id"])
    assert updated["status"] == "interrupted"
    assert ("supervisor_interrupted", {"reason": "cancelled"}) in emitted


def test_execute_supervisor_run_marks_error_when_agent_returns_failure(
    db_session,
    monkeypatch,
):
    user_id = db_session.query(User).first().id
    session = session_store.create_session(user_id=user_id)
    emitted = []

    async def failed_run(*args, **kwargs):
        return {"success": False, "error": "主模型和备用模型均返回空响应"}

    async def capture_emit(event, data):
        emitted.append((event, data))

    monkeypatch.setattr(
        "routers.supervisor.supervisor_agent.run",
        failed_run,
    )

    from routers.supervisor import _execute_supervisor_run

    asyncio.run(
        _execute_supervisor_run(
            session_id=session["id"],
            user_message="写第一章",
            context={"session_id": session["id"]},
            wrapped_emit=capture_emit,
        )
    )

    updated = session_store.get_session(session["id"])
    assert updated["status"] == "error"
    assert (
        "error",
        {"message": "主模型和备用模型均返回空响应"},
    ) in emitted
