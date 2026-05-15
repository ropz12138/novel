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
