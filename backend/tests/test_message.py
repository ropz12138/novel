"""Tests for Message model and message_service."""
import sys
sys.path.insert(0, "/root/Novel/backend")

from unittest.mock import MagicMock, patch

from app.models.message_model import Message


class TestMessageModel:
    """Message model 字段和默认值测试"""

    def test_table_name(self):
        assert Message.__tablename__ == "messages"

    def test_fields_exist(self):
        columns = {c.name for c in Message.__table__.columns}
        expected = {"id", "session_id", "work_id", "role", "content", "meta", "sort_order", "created_at"}
        assert expected == columns

    def test_role_values(self):
        """role 字段是 String(20)，合法值包含 user/assistant/tool_call/tool_result/thinking"""
        valid_roles = {"user", "assistant", "tool_call", "tool_result", "thinking"}
        for role in valid_roles:
            msg = Message(session_id="s1", role=role, content="test")
            assert msg.role == role

    def test_defaults(self):
        msg = Message(session_id="s1", role="user", content="hello")
        assert msg.content == "hello"
        # meta / sort_order default 在 DB INSERT 时由 SQLAlchemy 设置
        assert msg.work_id is None


class TestMessageService:
    """message_service CRUD 测试"""

    def test_create_message_basic(self):
        from app.services import message_service
        db = MagicMock()
        mock_msg = MagicMock()
        mock_msg.id = "msg-1"
        mock_msg.session_id = "s1"
        mock_msg.role = "user"
        mock_msg.content = "你好"
        mock_msg.meta = {}
        mock_msg.sort_order = 0
        mock_msg.work_id = None
        mock_msg.created_at = "2026-01-01T00:00:00Z"

        with patch.object(message_service, "Message", return_value=mock_msg):
            result = message_service.create_message(db, session_id="s1", role="user", content="你好")
            db.add.assert_called_once_with(mock_msg)
            db.commit.assert_called_once()
            assert result == mock_msg

    def test_create_message_with_meta(self):
        from app.services import message_service
        db = MagicMock()
        meta = {"tool": "query_characters", "args": {"work_id": "w1"}}

        with patch.object(message_service, "Message") as MockMsg:
            mock_msg = MagicMock()
            MockMsg.return_value = mock_msg
            result = message_service.create_message(
                db, session_id="s1", role="tool_call",
                content="query_characters", meta=meta, sort_order=5
            )
            MockMsg.assert_called_once_with(
                session_id="s1", role="tool_call",
                content="query_characters", meta=meta,
                sort_order=5, work_id=None,
            )

    def test_get_messages_by_session(self):
        from app.services import message_service
        db = MagicMock()
        msg1 = MagicMock()
        msg1.role = "user"
        msg1.content = "hello"
        msg2 = MagicMock()
        msg2.role = "assistant"
        msg2.content = "hi"

        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [msg1, msg2]
        result = message_service.get_messages_by_session(db, "s1")
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[1].role == "assistant"

    def test_get_messages_by_session_empty(self):
        from app.services import message_service
        db = MagicMock()
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []
        result = message_service.get_messages_by_session(db, "nonexistent")
        assert result == []

    def test_get_session_title_from_first_user_message(self):
        """从 messages 中动态生成 session title"""
        from app.services import message_service
        db = MagicMock()
        msg = MagicMock()
        msg.role = "user"
        msg.content = "帮我创建一个关于末世的大纲"
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = msg

        title = message_service.get_session_title(db, "s1")
        assert "末世" in title
        assert len(title) <= 53  # 50 chars + "..."

    def test_get_session_title_no_messages(self):
        from app.services import message_service
        db = MagicMock()
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None

        title = message_service.get_session_title(db, "s1")
        assert title == "新对话"

    def test_delete_messages_by_session(self):
        from app.services import message_service
        db = MagicMock()
        msg1 = MagicMock()
        msg2 = MagicMock()
        db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [msg1, msg2]

        message_service.delete_messages_by_session(db, "s1")
        assert db.delete.call_count == 2
        db.commit.assert_called_once()

    def test_get_next_sort_order(self):
        """获取下一个 sort_order"""
        from app.services import message_service
        db = MagicMock()
        db.query.return_value.filter_by.return_value.count.return_value = 5

        next_order = message_service.get_next_sort_order(db, "s1")
        assert next_order == 5

    def test_get_next_sort_order_empty(self):
        from app.services import message_service
        db = MagicMock()
        db.query.return_value.filter_by.return_by.return_value.count.return_value = 0
        # Simulate no messages
        db.query.return_value.filter_by.return_value.count.return_value = 0

        next_order = message_service.get_next_sort_order(db, "s1")
        assert next_order == 0


class TestMessageOutSchema:
    """Message 输出 schema 测试"""

    def test_basic(self):
        from app.schemas.message_schema import MessageOut
        msg = MessageOut(
            id="msg-1",
            session_id="s1",
            role="user",
            content="hello",
            meta={},
            sort_order=0,
            created_at="2026-01-01T00:00:00Z",
        )
        assert msg.id == "msg-1"
        assert msg.role == "user"

    def test_with_work_id(self):
        from app.schemas.message_schema import MessageOut
        msg = MessageOut(
            id="msg-1",
            session_id="s1",
            work_id="w1",
            role="assistant",
            content="done",
            meta={"tool_calls": []},
            sort_order=2,
            created_at="2026-01-01T00:00:00Z",
        )
        assert msg.work_id == "w1"
        assert msg.meta == {"tool_calls": []}

    def test_work_id_nullable(self):
        from app.schemas.message_schema import MessageOut
        msg = MessageOut(
            id="msg-1",
            session_id="s1",
            role="user",
            content="hi",
            sort_order=0,
            created_at=None,
        )
        assert msg.work_id is None
