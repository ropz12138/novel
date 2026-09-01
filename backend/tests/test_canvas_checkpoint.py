"""画布 checkpoint 与编辑重发测试。"""
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
import database
from routers.auth import get_current_user
from models.user import User
from models.work import CanvasWork
from models.node import Node
from models.edge import Edge
from models.session import SupervisorSession, SupervisorMessage
from models.user_canvas_action import UserCanvasAction
from services.canvas_checkpoint_service import (
    capture_canvas_checkpoint,
    restore_canvas_from_checkpoint,
    prepare_edit_resend,
)
from services.message_langchain import db_message_dicts_to_langchain

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

    n1 = Node(sort_order=0, work_id=work.id, type="outline", title="N1", layer=0)
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

    n2 = Node(sort_order=0, work_id=work.id, type="chapter", title="N2", layer=3)
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

    n1 = Node(sort_order=0, work_id=work.id, type="outline", title="keep", layer=0)
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

    n2 = Node(sort_order=0, work_id=work.id, type="chapter", title="added", layer=3)
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


def test_prepare_edit_resend_keeps_attached_actions_as_excluded_history(
    db_session,
    mock_auth,
):
    work = _make_work(db_session, mock_auth.id)
    session = _make_session(db_session, mock_auth.id, work.id)
    db_session.add(SupervisorMessage(
        session_id=session.id,
        role="user",
        content="我修改了「第一章」节点。",
        work_id=work.id,
        sort_order=0,
        meta={"type": "user_canvas_actions"},
    ))
    original = _add_user_message(
        db_session,
        session.id,
        "继续写第二章",
        work.id,
        1,
    )
    capture_canvas_checkpoint(
        db_session,
        session_id=session.id,
        work_id=work.id,
        trigger_message_id=original.id,
        sort_order=original.sort_order,
    )
    db_session.add(SupervisorMessage(
        session_id=session.id,
        role="assistant",
        content="已完成",
        work_id=work.id,
        sort_order=2,
    ))
    db_session.commit()

    new_msg = prepare_edit_resend(
        db_session,
        session_id=session.id,
        work_id=work.id,
        message_id=original.id,
        new_content="继续写第三章",
    )

    messages = (
        db_session.query(SupervisorMessage)
        .filter_by(session_id=session.id)
        .order_by(SupervisorMessage.sort_order)
        .all()
    )
    assert [(m.role, m.content) for m in messages] == [
        ("user", "我修改了「第一章」节点。"),
        ("user", "继续写第三章"),
    ]
    assert messages[0].meta == {
        "type": "user_canvas_actions",
        "excluded_from_agent": True,
    }
    assert new_msg["sort_order"] == 1


def test_prepare_edit_resend_rejects_user_actions_message(
    db_session,
    mock_auth,
):
    work = _make_work(db_session, mock_auth.id)
    session = _make_session(db_session, mock_auth.id, work.id)
    actions_message = SupervisorMessage(
        session_id=session.id,
        role="user",
        content="我修改了「第一章」节点。",
        work_id=work.id,
        sort_order=0,
        meta={"type": "user_canvas_actions"},
    )
    db_session.add(actions_message)
    db_session.commit()
    db_session.refresh(actions_message)

    with pytest.raises(ValueError, match="用户操作消息不可编辑"):
        prepare_edit_resend(
            db_session,
            session_id=session.id,
            work_id=work.id,
            message_id=actions_message.id,
            new_content="篡改操作消息",
        )


def test_editing_older_turn_keeps_prior_actions_and_drops_current_and_later_actions(
    db_session,
    mock_auth,
):
    work = _make_work(db_session, mock_auth.id)
    session = _make_session(db_session, mock_auth.id, work.id)

    rows = [
        SupervisorMessage(
            session_id=session.id,
            role="user",
            content="更早的操作",
            work_id=work.id,
            sort_order=0,
            meta={"type": "user_canvas_actions"},
        ),
        SupervisorMessage(
            session_id=session.id,
            role="user",
            content="第一轮",
            work_id=work.id,
            sort_order=1,
        ),
        SupervisorMessage(
            session_id=session.id,
            role="assistant",
            content="第一轮回复",
            work_id=work.id,
            sort_order=2,
        ),
        SupervisorMessage(
            session_id=session.id,
            role="user",
            content="本轮操作",
            work_id=work.id,
            sort_order=3,
            meta={"type": "user_canvas_actions"},
        ),
        SupervisorMessage(
            session_id=session.id,
            role="user",
            content="第二轮",
            work_id=work.id,
            sort_order=4,
        ),
        SupervisorMessage(
            session_id=session.id,
            role="assistant",
            content="第二轮回复",
            work_id=work.id,
            sort_order=5,
        ),
        SupervisorMessage(
            session_id=session.id,
            role="user",
            content="更晚的操作",
            work_id=work.id,
            sort_order=6,
            meta={"type": "user_canvas_actions"},
        ),
        SupervisorMessage(
            session_id=session.id,
            role="user",
            content="第三轮",
            work_id=work.id,
            sort_order=7,
        ),
    ]
    db_session.add_all(rows)
    db_session.commit()
    target = rows[4]
    capture_canvas_checkpoint(
        db_session,
        session_id=session.id,
        work_id=work.id,
        trigger_message_id=target.id,
        sort_order=target.sort_order,
    )

    prepare_edit_resend(
        db_session,
        session_id=session.id,
        work_id=work.id,
        message_id=target.id,
        new_content="第二轮（编辑后）",
    )

    messages = (
        db_session.query(SupervisorMessage)
        .filter_by(session_id=session.id)
        .order_by(SupervisorMessage.sort_order)
        .all()
    )
    assert [m.content for m in messages] == [
        "更早的操作",
        "第一轮",
        "第一轮回复",
        "本轮操作",
        "第二轮（编辑后）",
    ]
    action_messages = [
        m
        for m in messages
        if (m.meta or {}).get("type") == "user_canvas_actions"
    ]
    assert [m.content for m in action_messages] == ["更早的操作", "本轮操作"]
    assert action_messages[0].meta == {"type": "user_canvas_actions"}
    assert action_messages[1].meta == {
        "type": "user_canvas_actions",
        "excluded_from_agent": True,
    }


def test_editing_history_removes_user_action_records_after_checkpoint(
    db_session,
    mock_auth,
):
    work = _make_work(db_session, mock_auth.id)
    session = _make_session(db_session, mock_auth.id, work.id)
    target = _add_user_message(
        db_session,
        session.id,
        "回到这里重写",
        work.id,
        0,
    )
    checkpoint = capture_canvas_checkpoint(
        db_session,
        session_id=session.id,
        work_id=work.id,
        trigger_message_id=target.id,
        sort_order=target.sort_order,
    )
    db_session.add_all([
        UserCanvasAction(
            work_id=work.id,
            user_id=mock_auth.id,
            action_type="update_node",
            target_id="before",
            target_type="chapter",
            target_title="快照前操作",
            created_at=checkpoint.created_at - timedelta(seconds=1),
        ),
        UserCanvasAction(
            work_id=work.id,
            user_id=mock_auth.id,
            action_type="update_node",
            target_id="after",
            target_type="chapter",
            target_title="快照后操作",
            created_at=checkpoint.created_at + timedelta(seconds=1),
        ),
    ])
    db_session.commit()

    prepare_edit_resend(
        db_session,
        session_id=session.id,
        work_id=work.id,
        message_id=target.id,
        new_content="重写后的消息",
    )

    actions = (
        db_session.query(UserCanvasAction)
        .filter_by(work_id=work.id)
        .order_by(UserCanvasAction.created_at)
        .all()
    )
    assert [action.target_title for action in actions] == ["快照前操作"]


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
