"""Tests for SupervisorSession and session service logic."""
import sys
sys.path.insert(0, "/root/Novel/backend")

from unittest.mock import MagicMock

from app.schemas.session_schema import SupervisorSessionOut


class TestSupervisorSessionOutSchema:
    def test_from_dict(self):
        data = {
            "id": "abc-123",
            "work_id": "work-456",
            "type": "supervisor",
            "title": "大纲编辑",
            "stage": "done",
            "status": "completed",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        out = SupervisorSessionOut.model_validate(data)
        assert out.id == "abc-123"
        assert out.type == "supervisor"
        assert out.stage == "done"
        assert out.status == "completed"

    def test_work_id_nullable(self):
        data = {
            "id": "abc-123",
            "work_id": None,
            "type": "supervisor",
            "title": "对话",
            "stage": "idle",
            "status": "running",
        }
        out = SupervisorSessionOut.model_validate(data)
        assert out.work_id is None


class TestSessionServiceFunctions:
    """Test service helper logic that doesn't require DB."""

    def test_get_session_title_no_messages(self):
        from app.services.session_service import get_session_title

        db = MagicMock()
        db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None

        title = get_session_title(db, "nonexistent-session")
        assert title == "新对话"

    def test_touch_session_is_noop(self):
        """touch_session is now a no-op after ChatSession removal."""
        from app.services.session_service import touch_session
        db = MagicMock()
        touch_session(db, "any-id")  # should not raise

    def test_delete_session_if_no_user_messages_deletes_orphan(self):
        from app.models.agent_model import SupervisorSession
        from app.models.message_model import Message
        from app.services.session_service import delete_session_if_no_user_messages

        db = MagicMock()
        msg_q = MagicMock()
        msg_q.filter_by.return_value.limit.return_value.first.return_value = None

        sess = MagicMock()
        sess_q = MagicMock()
        sess_q.filter_by.return_value.first.return_value = sess

        def query_side_effect(model):
            if model is Message.id:
                return msg_q
            if model is SupervisorSession:
                return sess_q
            return MagicMock()

        db.query.side_effect = query_side_effect

        assert delete_session_if_no_user_messages(db, "orphan-id") is True
        db.delete.assert_called_once_with(sess)
        db.commit.assert_called()

    def test_delete_session_if_no_user_messages_keeps_when_user_exists(self):
        from app.services.session_service import delete_session_if_no_user_messages

        db = MagicMock()
        db.query.return_value.filter_by.return_value.limit.return_value.first.return_value = MagicMock(
            id="msg-1"
        )

        assert delete_session_if_no_user_messages(db, "sess-1") is False
        db.delete.assert_not_called()
