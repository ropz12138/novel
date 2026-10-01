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


def test_stop_endpoint_returns_false_when_no_running_task(db_session):
    session = session_store.create_session(user_id=db_session.query(User).first().id)
    resp = client.post("/api/supervisor/stop", json={"session_id": session["id"]})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["stopped"] is False


def test_stop_cancels_background_supervisor_task(db_session, monkeypatch):
    user_id = db_session.query(User).first().id
    session = session_store.create_session(user_id=user_id)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hanging_run(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr("routers.supervisor._execute_supervisor_run", hanging_run)

    from routers import supervisor as supervisor_router

    async def _run():
        response = supervisor_router._stream_supervisor_run(
            session_id=session["id"],
            user_message="继续",
            work_id=None,
            user_id=user_id,
            context_node_ids=None,
        )
        stream = response.body_iterator
        await stream.__anext__()
        async def consume_stream():
            async for _ in stream:
                pass
        consume = asyncio.create_task(consume_stream())
        await started.wait()
        result = await supervisor_router.stop_supervisor_run(session["id"])
        assert result["stopped"] is True
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        consume.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consume

    asyncio.run(_run())


def test_second_request_waits_and_keeps_stream_alive(db_session, monkeypatch):
    from routers import supervisor as router
    from services.supervisor_stream_broker import supervisor_stream_broker
    from services.supervisor_run_queue import supervisor_run_queue

    user_id = db_session.query(User).first().id
    session = session_store.create_session(user_id=user_id)
    sid = session["id"]

    async def run():
        gate = asyncio.Event()
        started = []

        async def fake_run(message, context, emit):
            started.append(message)
            if message == "改":
                await gate.wait()
            await emit("supervisor_done", {"message": "完成"})
            return {"success": True}

        monkeypatch.setattr(router.supervisor_agent, "run", fake_run)
        kwargs = dict(session_id=sid, work_id=None, user_id=user_id, context_node_ids=None)
        router._stream_supervisor_run(user_message="改", **kwargs)
        await asyncio.sleep(0)
        original_stream = supervisor_stream_broker._streams[sid]
        router._stream_supervisor_run(user_message="继续", **kwargs)
        assert started == ["改"]
        assert supervisor_stream_broker._streams[sid] is original_stream
        assert not original_stream.done
        gate.set()
        await supervisor_run_queue.tasks[sid]
        assert started == ["改", "继续"]
        events = [event async for event in supervisor_stream_broker.subscribe(sid)]
        assert sum(name == "supervisor_done" for name, _ in events) == 1
        assert sum(name == "supervisor_turn_done" for name, _ in events) == 1
        assert original_stream.done

    asyncio.run(run())


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


def test_sse_disconnect_does_not_cancel_supervisor_run(db_session, monkeypatch):
    user_id = db_session.query(User).first().id
    session = session_store.create_session(user_id=user_id)
    agent_started = asyncio.Event()
    allow_agent_to_finish = asyncio.Event()
    agent_finished = asyncio.Event()

    async def detached_run(**kwargs):
        agent_started.set()
        await kwargs["wrapped_emit"]("stage_start", {"stage": "thinking"})
        await allow_agent_to_finish.wait()
        session_store.update_session(session["id"], stage="done", status="completed")
        agent_finished.set()

    monkeypatch.setattr("routers.supervisor._execute_supervisor_run", detached_run)

    from routers import supervisor as supervisor_router

    async def _run():
        response = supervisor_router._stream_supervisor_run(
            session_id=session["id"],
            user_message="继续",
            work_id=None,
            user_id=user_id,
            context_node_ids=None,
        )
        stream = response.body_iterator
        await stream.__anext__()
        await stream.__anext__()
        await agent_started.wait()
        await stream.aclose()

        assert session_store.get_session(session["id"])["status"] == "running"
        allow_agent_to_finish.set()
        await asyncio.wait_for(agent_finished.wait(), timeout=1)

    asyncio.run(_run())
    assert session_store.get_session(session["id"])["status"] == "completed"


def test_get_supervisor_session_returns_authoritative_status(db_session):
    user_id = db_session.query(User).first().id
    session = session_store.create_session(user_id=user_id)
    session_store.update_session(session["id"], stage="done", status="completed")

    response = client.post(
        "/api/supervisor-sessions/get",
        json={"session_id": session["id"]},
    )

    assert response.status_code == 200
    assert response.json()["id"] == session["id"]
    assert response.json()["status"] == "completed"
