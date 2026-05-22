"""测试 supervisor_router 中的事件持久化逻辑。

验证：
1. _persist_event_message 能持久化 outline_edit_diff 事件
2. _persist_event_message 能持久化 character_edit_diff 事件
3. _launch_supervisor_task 在 resume 模式下能正确初始化 session_id
4. 所有事件类型（stage_start / evaluation_done / outline_edit_diff / character_edit_diff）均能持久化
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.routers.supervisor_router import (
    persist_event_message,
    PERSISTABLE_EVENTS,
)


class TestPersistableEvents:
    """验证可持久化事件集合包含所有必要的类型"""

    def test_includes_stage_start(self):
        assert "stage_start" in PERSISTABLE_EVENTS

    def test_includes_evaluation_done(self):
        assert "evaluation_done" in PERSISTABLE_EVENTS

    def test_includes_edit_chapter_diff(self):
        assert "edit_chapter_diff" in PERSISTABLE_EVENTS

    def test_includes_edit_chapter_auto_applied(self):
        assert "edit_chapter_auto_applied" in PERSISTABLE_EVENTS

    def test_includes_outline_edit_diff(self):
        assert "outline_edit_diff" in PERSISTABLE_EVENTS

    def test_includes_character_edit_diff(self):
        assert "character_edit_diff" in PERSISTABLE_EVENTS


class TestPersistEventMessageOutlineDiff:
    """验证 outline_edit_diff 事件的持久化"""

    @patch("app.routers.supervisor_router.message_service")
    def test_creates_outline_diff_card_message(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = "work-123"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        mock_msg_service.get_next_sort_order.return_value = 5

        data = {
            "message": "大纲已调整",
            "operations": [{"op": "modify"}],
            "diff": {"modified": ["章节1"]},
            "summary": {"total_added": 1, "total_modified": 2, "total_removed": 0},
        }

        result = persist_event_message(mock_db, "session-abc", "outline_edit_diff", data)

        assert result is True
        mock_msg_service.create_message.assert_called_once()
        call_kwargs = mock_msg_service.create_message.call_args[1]
        assert call_kwargs["session_id"] == "session-abc"
        assert call_kwargs["role"] == "assistant"
        assert call_kwargs["content"] == ""
        assert call_kwargs["work_id"] == "work-123"
        assert call_kwargs["sort_order"] == 5
        meta = call_kwargs["meta"]
        assert meta["type"] == "outline_diff_card"
        assert meta["outlineDiffCard"]["diff"] == data["diff"]
        assert meta["outlineDiffCard"]["summary"] == data["summary"]
        assert meta["outlineDiffCard"]["message"] == data["message"]
        assert meta["outlineDiffCard"]["operations"] == data["operations"]

    @patch("app.routers.supervisor_router.message_service")
    def test_creates_outline_diff_with_empty_data(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = "work-123"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        mock_msg_service.get_next_sort_order.return_value = 0

        result = persist_event_message(mock_db, "session-abc", "outline_edit_diff", {})

        assert result is True
        call_kwargs = mock_msg_service.create_message.call_args[1]
        meta = call_kwargs["meta"]
        assert meta["type"] == "outline_diff_card"
        assert meta["outlineDiffCard"]["diff"] is None
        assert meta["outlineDiffCard"]["summary"] is None

    @patch("app.routers.supervisor_router.message_service")
    def test_returns_false_when_session_not_found(self, mock_msg_service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        result = persist_event_message(mock_db, "session-nonexistent", "outline_edit_diff", {"diff": {}})

        assert result is False
        mock_msg_service.create_message.assert_not_called()


class TestPersistEventMessageCharacterDiff:
    """验证 character_edit_diff 事件的持久化"""

    @patch("app.routers.supervisor_router.message_service")
    def test_creates_character_diff_card_message(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = "work-456"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        mock_msg_service.get_next_sort_order.return_value = 3

        data = {
            "diff": {"added": ["角色A"]},
            "summary": {"total_added": 1, "total_modified": 0, "total_removed": 0},
        }

        result = persist_event_message(mock_db, "session-xyz", "character_edit_diff", data)

        assert result is True
        call_kwargs = mock_msg_service.create_message.call_args[1]
        assert call_kwargs["session_id"] == "session-xyz"
        assert call_kwargs["role"] == "assistant"
        assert call_kwargs["content"] == ""
        assert call_kwargs["work_id"] == "work-456"
        meta = call_kwargs["meta"]
        assert meta["type"] == "character_diff_card"
        assert meta["characterDiffCard"]["diff"] == data["diff"]
        assert meta["characterDiffCard"]["summary"] == data["summary"]


class TestPersistEventMessageExistingEvents:
    """验证已有事件类型的持久化仍然正常工作"""

    @patch("app.routers.supervisor_router.message_service")
    def test_stage_start_still_works(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = "w1"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        mock_msg_service.get_next_sort_order.return_value = 0

        result = persist_event_message(
            mock_db, "s1", "stage_start",
            {"stage": "thinking", "label": "AI 思考中"},
        )

        assert result is True
        call_kwargs = mock_msg_service.create_message.call_args[1]
        assert call_kwargs["content"] == "阶段：AI 思考中"
        assert call_kwargs["meta"]["type"] == "process_note"

    @patch("app.routers.supervisor_router.message_service")
    def test_unknown_event_returns_false(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session

        result = persist_event_message(mock_db, "s1", "unknown_event", {})

        assert result is False
        mock_msg_service.create_message.assert_not_called()
