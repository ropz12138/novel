"""会话历史分页：只返回末尾可见消息，diff 详情单独取。"""
from fastapi.testclient import TestClient

from main import app
import database
from models.user import User
from routers.auth import get_current_user
from services.session_store import session_store


client = TestClient(app)


def _auth_user():
    db = database.SessionLocal()
    user = User(username="owner", email="owner@t.t", password_hash="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def test_history_page_returns_the_tail_and_omits_tool_results():
    user = _auth_user()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        session = session_store.create_session(user_id=user.id)
        for index in range(3):
            session_store.add_message(session["id"], "user", f"u{index}")
            session_store.add_message(
                session["id"],
                "tool_result",
                f"secret-{index}",
                meta={"tool_name": "read_node_content"},
            )
            session_store.add_message(session["id"], "assistant", f"a{index}")

        response = client.post(
            "/api/supervisor-sessions/messages",
            json={"session_id": session["id"], "limit": 2},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["has_more"] is True
        assert [(row["role"], row["content"]) for row in body["messages"]] == [
            ("user", "u2"),
            ("assistant", "a2"),
        ]
        stored = session_store.get_messages(session["id"])
        assert any(row["role"] == "tool_result" and row["content"] == "secret-0" for row in stored)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_history_page_keeps_a_tool_call_run_together_and_drops_call_payloads():
    user = _auth_user()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        session = session_store.create_session(user_id=user.id)
        session_store.add_message(session["id"], "user", "先看")
        for index in range(3):
            session_store.add_message(
                session["id"],
                "tool_call",
                "read_node_content",
                meta={
                    "args": {"node_id": f"n{index}"},
                    "tool_call_id": f"call-{index}",
                    "success": False,
                    "reasoning_content": "很长的思考",
                },
            )
        session_store.add_message(session["id"], "assistant", "看完了")

        response = client.post(
            "/api/supervisor-sessions/messages",
            json={"session_id": session["id"], "limit": 2},
        )
        body = response.json()
        assert body["has_more"] is True
        assert [row["role"] for row in body["messages"]] == [
            "tool_call",
            "tool_call",
            "tool_call",
            "assistant",
        ]
        assert body["messages"][0]["meta"] == {"tool_call_id": "call-0", "success": False}
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_earlier_page_uses_before_sort_order():
    user = _auth_user()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        session = session_store.create_session(user_id=user.id)
        for index in range(5):
            session_store.add_message(session["id"], "user", f"u{index}")

        first = client.post(
            "/api/supervisor-sessions/messages",
            json={"session_id": session["id"], "limit": 2},
        ).json()
        assert [row["content"] for row in first["messages"]] == ["u3", "u4"]
        cursor = first["messages"][0]["sort_order"]

        second = client.post(
            "/api/supervisor-sessions/messages",
            json={"session_id": session["id"], "limit": 2, "before_sort_order": cursor},
        ).json()
        assert [row["content"] for row in second["messages"]] == ["u1", "u2"]
        assert second["has_more"] is True

        third = client.post(
            "/api/supervisor-sessions/messages",
            json={
                "session_id": session["id"],
                "limit": 2,
                "before_sort_order": second["messages"][0]["sort_order"],
            },
        ).json()
        assert [row["content"] for row in third["messages"]] == ["u0"]
        assert third["has_more"] is False
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_diff_page_is_summary_and_detail_returns_hunks_only():
    user = _auth_user()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        session = session_store.create_session(user_id=user.id)
        saved = session_store.add_message(
            session["id"],
            "assistant",
            "",
            meta={
                "type": "chapter_content_diff_card",
                "chapterContentDiffCard": {
                    "title": "第一章",
                    "node_type": "chapter",
                    "summary": {"paragraphs_changed": 1},
                    "word_count": 120,
                    "word_count_delta": 3,
                    "hunks": [{"type": "replace", "old_text": "旧", "new_text": "新"}],
                    "original_content": "旧全文",
                    "current_content": "新全文",
                    "baseline_content": "基线全文",
                },
            },
        )

        page = client.post(
            "/api/supervisor-sessions/messages",
            json={"session_id": session["id"]},
        ).json()
        card = page["messages"][0]["meta"]["chapterContentDiffCard"]
        assert card["title"] == "第一章"
        assert card["summary"] == {"paragraphs_changed": 1}
        assert card["word_count"] == 120
        assert "hunks" not in card
        assert "original_content" not in card
        assert "current_content" not in card
        assert "baseline_content" not in card

        detail = client.post(
            "/api/supervisor-sessions/messages/diff",
            json={"session_id": session["id"], "message_id": saved["id"]},
        )
        assert detail.status_code == 200
        assert detail.json() == {
            "hunks": [{"type": "replace", "old_text": "旧", "new_text": "新"}],
        }
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_history_page_loads_when_a_todolist_message_exists():
    user = _auth_user()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        session = session_store.create_session(user_id=user.id)
        session_store.add_message(
            session["id"],
            "assistant",
            "",
            meta={
                "type": "requirements_todolist",
                "todoCard": {
                    "intent_summary": "写下一章",
                    "todolist": [],
                    "ready_to_execute": True,
                },
            },
        )
        session_store.add_message(session["id"], "user", "继续")

        response = client.post(
            "/api/supervisor-sessions/messages",
            json={"session_id": session["id"]},
        )
        assert response.status_code == 200
        body = response.json()
        assert [row["content"] for row in body["messages"]] == ["", "继续"]
        assert body["messages"][0]["meta"]["type"] == "requirements_todolist"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
