"""画布 checkpoint 与编辑重发测试。"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import database
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node
from app.models.edge import Edge
from app.models.session import SupervisorSession, SupervisorMessage
from app.services.canvas_checkpoint_service import (
    capture_canvas_checkpoint,
    restore_canvas_from_checkpoint,
    prepare_edit_resend,
)
from app.services.message_langchain import db_message_dicts_to_langchain

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="cp_tester", email="cp@t.t", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def _make_work(db, user_id):
    work = CanvasWork(user_id=user_id, title="cp-work")
    db.add(work)
    db.commit()
    db.refresh(work)
    return work


def _make_session(db, user_id, work_id):
    session = SupervisorSession(user_id=user_id, work_id=work_id, title="t")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _add_user_message(db, session_id, content, work_id, sort_order):
    msg = SupervisorMessage(
        session_id=session_id,
        role="user",
        content=content,
        work_id=work_id,
        sort_order=sort_order,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def test_capture_and_restore_canvas_checkpoint(db_session, mock_auth):
    work = _make_work(db_session, mock_auth.id)
    session = _make_session(db_session, mock_auth.id, work.id)

    n1 = Node(work_id=work.id, type="outline", title="N1", layer=0)
    db_session.add(n1)
    db_session.commit()
    db_session.refresh(n1)

    m1 = _add_user_message(db_session, session.id, "hello", work.id, 0)
    cp = capture_canvas_checkpoint(
        db_session,
        session_id=session.id,
        work_id=work.id,
        trigger_message_id=m1.id,
        sort_order=m1.sort_order,
    )
    assert cp.node_count == 1

    n2 = Node(work_id=work.id, type="chapter", title="N2", layer=3)
    db_session.add(n2)
    db_session.commit()

    restore_canvas_from_checkpoint(db_session, work.id, cp.id)
    db_session.expire_all()

    nodes = db_session.query(Node).filter(Node.work_id == work.id).all()
    assert len(nodes) == 1
    assert nodes[0].id == n1.id


def test_prepare_edit_resend_restores_and_truncates(db_session, mock_auth):
    work = _make_work(db_session, mock_auth.id)
    session = _make_session(db_session, mock_auth.id, work.id)

    n1 = Node(work_id=work.id, type="outline", title="keep", layer=0)
    db_session.add(n1)
    db_session.commit()
    db_session.refresh(n1)

    m1 = _add_user_message(db_session, session.id, "第一轮", work.id, 0)
    capture_canvas_checkpoint(
        db_session,
        session_id=session.id,
        work_id=work.id,
        trigger_message_id=m1.id,
        sort_order=m1.sort_order,
    )
    db_session.add(SupervisorMessage(
        session_id=session.id, role="assistant", content="A1", work_id=work.id, sort_order=1,
    ))

    m2 = _add_user_message(db_session, session.id, "第二轮", work.id, 2)
    capture_canvas_checkpoint(
        db_session,
        session_id=session.id,
        work_id=work.id,
        trigger_message_id=m2.id,
        sort_order=m2.sort_order,
    )

    n2 = Node(work_id=work.id, type="chapter", title="added", layer=3)
    db_session.add(n2)
    db_session.commit()

    db_session.add(SupervisorMessage(
        session_id=session.id, role="assistant", content="A2", work_id=work.id, sort_order=3,
    ))
    db_session.commit()

    new_msg = prepare_edit_resend(
        db_session,
        session_id=session.id,
        work_id=work.id,
        message_id=m2.id,
        new_content="第二轮-编辑后",
    )

    db_session.expire_all()
    nodes = db_session.query(Node).filter(Node.work_id == work.id).all()
    assert len(nodes) == 1
    assert nodes[0].title == "keep"

    msgs = (
        db_session.query(SupervisorMessage)
        .filter_by(session_id=session.id)
        .order_by(SupervisorMessage.sort_order)
        .all()
    )
    roles_contents = [(m.role, m.content) for m in msgs]
    assert roles_contents == [
        ("user", "第一轮"),
        ("assistant", "A1"),
        ("user", "第二轮-编辑后"),
    ]
    assert new_msg["role"] == "user"
    assert new_msg["content"] == "第二轮-编辑后"


def test_db_message_dicts_to_langchain_tool_chain():
    messages = [
        {"role": "user", "content": "查一下", "meta": {}, "sort_order": 0},
        {
            "role": "tool_call",
            "content": "get_canvas_index",
            "meta": {"args": {"reason": "x"}, "tool_call_id": "call_1"},
            "sort_order": 1,
        },
        {
            "role": "tool_result",
            "content": '{"nodes": []}',
            "meta": {"tool_call_id": "call_1", "tool_name": "get_canvas_index"},
            "sort_order": 2,
        },
        {"role": "assistant", "content": "看完了", "meta": {}, "sort_order": 3},
        {"role": "user", "content": "继续", "meta": {}, "sort_order": 4},
    ]
    lc = db_message_dicts_to_langchain(messages[:-1])
    assert len(lc) == 4
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    assert isinstance(lc[0], HumanMessage)
    assert isinstance(lc[1], AIMessage)
    assert lc[1].tool_calls[0]["name"] == "get_canvas_index"
    assert isinstance(lc[2], ToolMessage)
    assert lc[2].content == '{"nodes": []}'
    assert isinstance(lc[3], AIMessage)
