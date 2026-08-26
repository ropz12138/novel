"""Todolist 消息持久化与历史恢复测试。"""
import uuid

import pytest
from sqlalchemy.orm.attributes import flag_modified

from models.session import SupervisorMessage, SupervisorSession
from models.user import User
from services.supervisor_event_persist import (
    PERSISTABLE_TODO_EVENTS,
    enrich_messages_with_todolist,
    persist_supervisor_event,
)
from services.todo_service import update_todolist, write_todolist


def _setup_session(db):
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


def test_persist_todolist_generated_creates_message(db_session):
    session_id = _setup_session(db_session)
    result = write_todolist(session_id, ["任务A"], db_session)
    items = result.events[0][1]["todolist"]
    persist_supervisor_event(
        db_session,
        session_id,
        "todolist_generated",
        {"todolist": items, "ready_to_execute": True},
    )

    msgs = db_session.query(SupervisorMessage).filter_by(session_id=session_id).all()
    assert len(msgs) == 1
    assert msgs[0].meta["type"] == "requirements_todolist"
    assert msgs[0].meta["todoCard"]["todolist"][0]["task"] == "任务A"


def test_persist_task_status_updated_mutates_existing_card(db_session):
    session_id = _setup_session(db_session)
    write_todolist(session_id, ["任务A"], db_session)
    items = db_session.query(__import__("models.todo_item", fromlist=["TodoItem"]).TodoItem).filter_by(session_id=session_id).all()
    db_id = items[0].id

    persist_supervisor_event(
        db_session,
        session_id,
        "todolist_generated",
        {
            "todolist": [{"db_id": db_id, "task_id": "T1", "task": "任务A", "status": "pending"}],
            "ready_to_execute": True,
        },
    )
    update_todolist(session_id, "complete", db_session, task_id="T1")
    persist_supervisor_event(
        db_session,
        session_id,
        "task_status_updated",
        {
            "task_item_id": db_id,
            "task_id": "T1",
            "old_status": "pending",
            "new_status": "completed",
        },
    )

    msg = db_session.query(SupervisorMessage).filter_by(session_id=session_id).one()
    assert msg.meta["todoCard"]["todolist"][0]["status"] == "completed"


def test_enrich_messages_from_todo_items_when_no_message(db_session):
    session_id = _setup_session(db_session)
    write_todolist(session_id, ["持久化任务"], db_session)

    enriched = enrich_messages_with_todolist(db_session, session_id, [])
    assert len(enriched) == 1
    assert enriched[0]["meta"]["type"] == "requirements_todolist"
    assert enriched[0]["meta"]["todoCard"]["todolist"][0]["task"] == "持久化任务"


def test_enrich_messages_syncs_latest_status(db_session):
    session_id = _setup_session(db_session)
    write_todolist(session_id, ["任务A"], db_session)
    from models.todo_item import TodoItem

    todo = db_session.query(TodoItem).filter_by(session_id=session_id).first()
    persist_supervisor_event(
        db_session,
        session_id,
        "todolist_generated",
        {
            "todolist": [{"db_id": todo.id, "task_id": "T1", "task": "任务A", "status": "pending"}],
            "ready_to_execute": True,
        },
    )
    update_todolist(session_id, "complete", db_session, task_id="T1")

    msg_dict = {
        "role": "assistant",
        "content": "",
        "meta": {
            "type": "requirements_todolist",
            "todoCard": {
                "todolist": [{"db_id": todo.id, "task_id": "T1", "task": "任务A", "status": "pending"}],
                "ready_to_execute": True,
            },
        },
    }
    enriched = enrich_messages_with_todolist(db_session, session_id, [msg_dict])
    assert enriched[0]["meta"]["todoCard"]["todolist"][0]["status"] == "completed"


def test_persistable_events_include_todo(db_session):
    for ev in (
        "todolist_generated",
        "task_status_updated",
        "todolist_task_added",
        "todolist_task_edited",
        "todolist_task_deleted",
    ):
        assert ev in PERSISTABLE_TODO_EVENTS


def test_tool_call_sort_order_before_todolist_card(db_session):
    """write_todolist 的 tool_call 必须先于 requirements_todolist 入库，history 顺序才与流式一致。"""
    from langchain_core.messages import AIMessage

    from services.agents.supervisor import SupervisorAgent
    from services.session_store import session_store

    session_id = _setup_session(db_session)
    agent = SupervisorAgent()
    agent._save_intermediate_messages(
        session_id,
        [
            AIMessage(
                content="我来规划任务清单",
                tool_calls=[{
                    "id": "call_todo",
                    "name": "write_todolist",
                    "args": {"tasks": ["任务A"]},
                }],
            )
        ],
    )

    result = write_todolist(session_id, ["任务A"], db_session)
    items = result.events[0][1]["todolist"]
    persist_supervisor_event(
        db_session,
        session_id,
        "todolist_generated",
        {"todolist": items, "ready_to_execute": True},
    )

    msgs = session_store.get_messages(session_id)
    tool_idx = next(i for i, m in enumerate(msgs) if m["role"] == "tool_call")
    todo_idx = next(
        i for i, m in enumerate(msgs)
        if m.get("meta", {}).get("type") == "requirements_todolist"
    )
    assert tool_idx < todo_idx
    assert msgs[tool_idx]["content"] == "write_todolist"


@pytest.fixture
def db_session(isolated_db):
    from database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
