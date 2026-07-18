"""Todolist 工具测试 — write_todolist / update_todolist（无类型、无内部 LLM）。"""
import uuid

import pytest

from app.models.session import SupervisorSession
from app.models.user import User
from app.services.todo_service import (
    MAX_TODO_TASKS,
    list_todo_items,
    serialize_todo_item,
    update_todolist,
    write_todolist,
)


def _create_session(db):
    user = User(
        id=str(uuid.uuid4()),
        username=f"user_{uuid.uuid4().hex[:8]}",
        email=f"{uuid.uuid4().hex}@test.local",
        password_hash="hash",
    )
    db.add(user)
    db.flush()
    session = SupervisorSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session.id


def test_write_todolist_creates_numbered_tasks(db_session):
    session_id = _create_session(db_session)
    result = write_todolist(session_id, ["梳理世界观", "撰写第一章"], db_session)
    assert result.ok
    assert "2" in result.message
    items = list_todo_items(db_session, session_id)
    assert len(items) == 2
    assert items[0].task_id == "T1"
    assert items[0].task == "梳理世界观"
    assert items[0].status == "pending"
    assert items[1].task_id == "T2"


def test_write_todolist_rejects_empty_list(db_session):
    session_id = _create_session(db_session)
    result = write_todolist(session_id, [], db_session)
    assert not result.ok
    assert "空" in result.message


def test_write_todolist_rejects_blank_task(db_session):
    session_id = _create_session(db_session)
    result = write_todolist(session_id, ["有效任务", "  "], db_session)
    assert not result.ok


def test_write_todolist_rejects_too_many_tasks(db_session):
    session_id = _create_session(db_session)
    tasks = [f"任务{i}" for i in range(MAX_TODO_TASKS + 1)]
    result = write_todolist(session_id, tasks, db_session)
    assert not result.ok
    assert str(MAX_TODO_TASKS) in result.message


def test_write_todolist_replaces_existing(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["旧任务"], db_session)
    write_todolist(session_id, ["新任务A", "新任务B"], db_session)
    items = list_todo_items(db_session, session_id)
    assert len(items) == 2
    assert items[0].task == "新任务A"


def test_write_todolist_emits_event(db_session):
    session_id = _create_session(db_session)
    result = write_todolist(session_id, ["任务一"], db_session)
    assert result.events
    assert result.events[0][0] == "todolist_generated"
    payload = result.events[0][1]
    assert len(payload["todolist"]) == 1
    assert payload["todolist"][0]["task"] == "任务一"
    assert payload["ready_to_execute"] is True


def test_update_complete_marks_task(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["任务A", "任务B"], db_session)
    result = update_todolist(session_id, "complete", db_session, task_id="T1")
    assert result.ok
    assert "T1" in result.message
    items = list_todo_items(db_session, session_id)
    assert items[0].status == "completed"
    assert items[1].status == "pending"


def test_update_complete_rejects_unknown_task(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["任务A"], db_session)
    result = update_todolist(session_id, "complete", db_session, task_id="T9")
    assert not result.ok
    assert "不存在" in result.message


def test_update_complete_rejects_already_completed(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["任务A"], db_session)
    update_todolist(session_id, "complete", db_session, task_id="T1")
    result = update_todolist(session_id, "complete", db_session, task_id="T1")
    assert not result.ok


def test_update_add_appends_pending_tasks(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["任务A"], db_session)
    result = update_todolist(session_id, "add", db_session, tasks=["任务B"])
    assert result.ok
    assert "T2" in result.message
    items = list_todo_items(db_session, session_id)
    assert len(items) == 2
    assert items[1].task == "任务B"


def test_update_edit_pending_task(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["旧描述"], db_session)
    result = update_todolist(session_id, "edit", db_session, task_id="T1", task="新描述")
    assert result.ok
    item = list_todo_items(db_session, session_id)[0]
    assert item.task == "新描述"


def test_update_edit_rejects_completed(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["任务A"], db_session)
    update_todolist(session_id, "complete", db_session, task_id="T1")
    result = update_todolist(session_id, "edit", db_session, task_id="T1", task="改不了")
    assert not result.ok


def test_update_remove_pending_task(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["保留", "删除"], db_session)
    result = update_todolist(session_id, "remove", db_session, task_id="T2")
    assert result.ok
    items = list_todo_items(db_session, session_id)
    assert len(items) == 1
    assert items[0].task == "保留"


def test_update_remove_rejects_completed(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["任务A"], db_session)
    update_todolist(session_id, "complete", db_session, task_id="T1")
    result = update_todolist(session_id, "remove", db_session, task_id="T1")
    assert not result.ok


def test_update_invalid_action(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["任务A"], db_session)
    result = update_todolist(session_id, "noop", db_session, task_id="T1")
    assert not result.ok
    assert "无效" in result.message


def test_serialize_todo_item(db_session):
    session_id = _create_session(db_session)
    write_todolist(session_id, ["示例"], db_session)
    item = list_todo_items(db_session, session_id)[0]
    data = serialize_todo_item(item)
    assert data["db_id"] == item.id
    assert data["task_id"] == "T1"
    assert data["task"] == "示例"
    assert data["status"] == "pending"


@pytest.fixture
def db_session(isolated_db):
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
