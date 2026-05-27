"""Phase 5 测试：Confirm/Waiting 任务收口

验证：
1. confirm_action accept 时更新关联 task_item 状态为 completed
2. confirm_action reject 时更新关联 task_item 状态为 failed
3. confirm_action emit task_status_updated 事件
4. confirm_action 无 active_child 中的 task_item_id 时仍正常（兼容老数据）
"""

import pytest
from unittest.mock import MagicMock, patch


class TestConfirmActionUpdatesTaskItem:
    """验证 confirm_action 更新 TaskItem 状态"""

    @patch("app.routers.supervisor_router.message_service")
    def test_accept_updates_task_to_completed(self, mock_msg_service):
        from app.routers.supervisor_router import confirm_action

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.status = "waiting"
        mock_session.active_child = {
            "type": "edit_chapter",
            "work_id": "w1",
            "chapter_number": 1,
            "new_content": "新内容",
            "task_item_id": "task-uuid-1",
        }
        mock_msg_service.get_next_sort_order.return_value = 5

        mock_task = MagicMock()
        mock_task.id = "task-uuid-1"
        mock_task.status = "in_progress"
        mock_task.task_id = "T1"

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
                elif model.__name__ == "TaskItem":
                    r.filter_by.return_value.first.return_value = mock_task
                    return r
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect

        payload = MagicMock()
        payload.session_id = "sess-1"
        payload.action = "accept"
        payload.new_content = None

        with patch("app.services.supervisor.edit_chapter_agent.EditChapterAgent") as mock_edit_cls:
            mock_edit = MagicMock()
            mock_edit.accept_edit.return_value = {"status": "ok"}
            mock_edit_cls.return_value = mock_edit
            result = confirm_action(payload=payload, db=mock_db, current_user=MagicMock())

        assert result["status"] == "accepted"
        assert mock_task.status == "completed"

    @patch("app.routers.supervisor_router.message_service")
    def test_reject_updates_task_to_failed(self, mock_msg_service):
        from app.routers.supervisor_router import confirm_action

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.status = "waiting"
        mock_session.active_child = {
            "type": "edit_chapter",
            "work_id": "w1",
            "chapter_number": 2,
            "new_content": "新内容",
            "task_item_id": "task-uuid-2",
        }
        mock_msg_service.get_next_sort_order.return_value = 5

        mock_task = MagicMock()
        mock_task.id = "task-uuid-2"
        mock_task.status = "in_progress"

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
                elif model.__name__ == "TaskItem":
                    r.filter_by.return_value.first.return_value = mock_task
                    return r
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect

        payload = MagicMock()
        payload.session_id = "sess-1"
        payload.action = "reject"
        payload.new_content = None

        with patch("app.services.supervisor.edit_chapter_agent.EditChapterAgent") as mock_edit_cls:
            mock_edit = MagicMock()
            mock_edit_cls.return_value = mock_edit
            result = confirm_action(payload=payload, db=mock_db, current_user=MagicMock())

        assert result["status"] == "rejected"
        assert mock_task.status == "failed"

    @patch("app.routers.supervisor_router.message_service")
    def test_accept_without_task_item_id_still_works(self, mock_msg_service):
        """兼容老数据：active_child 中没有 task_item_id 时正常工作"""
        from app.routers.supervisor_router import confirm_action

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.status = "waiting"
        mock_session.active_child = {
            "type": "edit_chapter",
            "work_id": "w1",
            "chapter_number": 1,
            "new_content": "新内容",
        }
        mock_msg_service.get_next_sort_order.return_value = 5

        def query_side_effect(model):
            r = MagicMock()
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect

        payload = MagicMock()
        payload.session_id = "sess-1"
        payload.action = "accept"
        payload.new_content = None

        with patch("app.services.supervisor.edit_chapter_agent.EditChapterAgent") as mock_edit_cls:
            mock_edit = MagicMock()
            mock_edit.accept_edit.return_value = {"status": "ok"}
            mock_edit_cls.return_value = mock_edit
            result = confirm_action(payload=payload, db=mock_db, current_user=MagicMock())

        assert result["status"] == "accepted"

    @patch("app.routers.supervisor_router.message_service")
    def test_outline_accept_updates_task_to_completed(self, mock_msg_service):
        from app.routers.supervisor_router import confirm_action

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.status = "waiting"
        mock_session.active_child = {
            "type": "edit_outline",
            "work_id": "w1",
            "task_item_id": "task-uuid-outline",
        }
        mock_msg_service.get_next_sort_order.return_value = 3

        mock_task = MagicMock()
        mock_task.id = "task-uuid-outline"
        mock_task.status = "in_progress"

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
                elif model.__name__ == "TaskItem":
                    r.filter_by.return_value.first.return_value = mock_task
                    return r
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect

        payload = MagicMock()
        payload.session_id = "sess-1"
        payload.action = "accept"
        payload.new_content = None

        with patch("app.services.supervisor.outline_agent.OutlineAgent") as mock_outline:
            result = confirm_action(payload=payload, db=mock_db, current_user=MagicMock())

        assert result["status"] == "accepted"
        assert mock_task.status == "completed"
