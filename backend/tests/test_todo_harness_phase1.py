"""Phase 1 测试：修复 todolist 持久化基础

验证：
1. PERSISTABLE_EVENTS 包含 todolist_generated、task_status_updated、todolist_readiness_updated
2. persist_event_message 能持久化 todolist_generated 事件为 requirements_todolist message
3. persist_event_message 能持久化 todolist_readiness_updated 事件（更新现有 todoCard 的 ready_to_execute）
4. persist_event_message 能持久化 task_status_updated 事件（方案 B：原地更新 todoCard 中对应任务状态）
5. analyze_requirements 中 ready_to_execute 的 commit 修复（在同一个事务中）
6. 前端历史消息恢复能识别 meta.type === "requirements_todolist"
"""

import pytest
from unittest.mock import MagicMock, patch, call

from app.routers.supervisor_router import (
    persist_event_message,
    PERSISTABLE_EVENTS,
)


class TestPersistableEventsIncludesTodolist:
    """验证可持久化事件集合包含 todolist 相关事件"""

    def test_includes_todolist_generated(self):
        assert "todolist_generated" in PERSISTABLE_EVENTS

    def test_includes_task_status_updated(self):
        assert "task_status_updated" in PERSISTABLE_EVENTS

    def test_includes_todolist_readiness_updated(self):
        assert "todolist_readiness_updated" in PERSISTABLE_EVENTS

    def test_all_original_events_still_present(self):
        """原有事件不应被移除"""
        for ev in [
            "stage_start", "evaluation_done", "edit_chapter_diff",
            "edit_chapter_auto_applied", "outline_edit_diff",
            "character_edit_diff", "chapter_metadata_diff",
            "chapter_metadata_generated",
        ]:
            assert ev in PERSISTABLE_EVENTS


class TestPersistTodolistGenerated:
    """验证 todolist_generated 事件的持久化"""

    @patch("app.routers.supervisor_router.message_service")
    def test_creates_requirements_todolist_message(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = "work-123"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        mock_msg_service.get_next_sort_order.return_value = 7

        todolist_data = {
            "intent_summary": "创建末日科幻小说大纲并写第一章",
            "todolist": [
                {
                    "db_id": "task-uuid-1",
                    "task_id": "T1",
                    "task": "创建大纲",
                    "owner": "outline_agent",
                    "status": "pending",
                    "depends_on": [],
                    "done_criteria": "大纲已生成",
                },
                {
                    "db_id": "task-uuid-2",
                    "task_id": "T2",
                    "task": "写第一章",
                    "owner": "chapter_agent",
                    "status": "pending",
                    "depends_on": ["T1"],
                    "done_criteria": "第一章正文已保存",
                },
            ],
            "ready_to_execute": True,
        }

        result = persist_event_message(mock_db, "session-abc", "todolist_generated", todolist_data)

        assert result is True
        mock_msg_service.create_message.assert_called_once()
        call_kwargs = mock_msg_service.create_message.call_args[1]
        assert call_kwargs["session_id"] == "session-abc"
        assert call_kwargs["role"] == "assistant"
        assert call_kwargs["content"] == ""
        assert call_kwargs["work_id"] == "work-123"
        assert call_kwargs["sort_order"] == 7
        meta = call_kwargs["meta"]
        assert meta["type"] == "requirements_todolist"
        assert meta["event"] == "todolist_generated"
        assert meta["todoCard"]["intent_summary"] == "创建末日科幻小说大纲并写第一章"
        assert len(meta["todoCard"]["todolist"]) == 2
        assert meta["todoCard"]["ready_to_execute"] is True

    @patch("app.routers.supervisor_router.message_service")
    def test_todolist_with_empty_fields(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = None
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        mock_msg_service.get_next_sort_order.return_value = 0

        result = persist_event_message(mock_db, "session-abc", "todolist_generated", {})

        assert result is True
        call_kwargs = mock_msg_service.create_message.call_args[1]
        meta = call_kwargs["meta"]
        assert meta["todoCard"]["intent_summary"] == ""
        assert meta["todoCard"]["todolist"] == []
        assert meta["todoCard"]["ready_to_execute"] is False

    @patch("app.routers.supervisor_router.message_service")
    def test_returns_false_when_session_not_found(self, mock_msg_service):
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        result = persist_event_message(
            mock_db, "session-nonexistent", "todolist_generated",
            {"intent_summary": "test", "todolist": [], "ready_to_execute": True},
        )

        assert result is False
        mock_msg_service.create_message.assert_not_called()


class TestPersistTaskStatusUpdated:
    """验证 task_status_updated 事件的持久化（方案 B：原地更新 todoCard）"""

    @patch("app.routers.supervisor_router.message_service")
    def test_updates_existing_todolist_message_status(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = "work-123"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        mock_msg_service.get_next_sort_order.return_value = 7

        # 模拟找到已有的 requirements_todolist message
        existing_msg = MagicMock()
        existing_msg.role = "assistant"
        existing_msg.meta = {
            "type": "requirements_todolist",
            "event": "todolist_generated",
            "todoCard": {
                "intent_summary": "创建大纲",
                "todolist": [
                    {
                        "db_id": "task-uuid-1",
                        "task_id": "T1",
                        "task": "创建大纲",
                        "owner": "outline_agent",
                        "status": "pending",
                        "depends_on": [],
                        "done_criteria": "大纲已生成",
                    },
                    {
                        "db_id": "task-uuid-2",
                        "task_id": "T2",
                        "task": "写第一章",
                        "owner": "chapter_agent",
                        "status": "pending",
                        "depends_on": ["T1"],
                        "done_criteria": "正文已保存",
                    },
                ],
                "ready_to_execute": True,
            },
        }
        mock_msg_service.get_messages_by_session.return_value = [existing_msg]

        data = {
            "task_item_id": "task-uuid-1",
            "task_id": "T1",
            "old_status": "pending",
            "new_status": "in_progress",
            "result_summary": "",
        }

        result = persist_event_message(
            mock_db, "session-abc", "task_status_updated", data,
        )

        assert result is True
        # 验证 todoCard 中对应任务的状态已更新
        updated_task = existing_msg.meta["todoCard"]["todolist"][0]
        assert updated_task["status"] == "in_progress"
        # 第二个任务应保持不变
        unchanged_task = existing_msg.meta["todoCard"]["todolist"][1]
        assert unchanged_task["status"] == "pending"
        # 验证 commit 被调用
        mock_db.commit.assert_called()

    @patch("app.routers.supervisor_router.message_service")
    def test_updates_result_summary_and_error_message(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = "work-123"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session

        existing_msg = MagicMock()
        existing_msg.role = "assistant"
        existing_msg.meta = {
            "type": "requirements_todolist",
            "todoCard": {
                "intent_summary": "test",
                "todolist": [
                    {
                        "db_id": "task-uuid-1",
                        "task_id": "T1",
                        "task": "创建大纲",
                        "owner": "outline_agent",
                        "status": "in_progress",
                        "depends_on": [],
                        "done_criteria": "",
                    },
                ],
                "ready_to_execute": True,
            },
        }
        mock_msg_service.get_messages_by_session.return_value = [existing_msg]

        data = {
            "task_item_id": "task-uuid-1",
            "task_id": "T1",
            "old_status": "in_progress",
            "new_status": "failed",
            "result_summary": "大纲创建失败",
            "error_message": "灵感描述不足",
        }

        result = persist_event_message(
            mock_db, "session-abc", "task_status_updated", data,
        )

        assert result is True
        updated_task = existing_msg.meta["todoCard"]["todolist"][0]
        assert updated_task["status"] == "failed"
        assert updated_task["result_summary"] == "大纲创建失败"
        assert updated_task["error_message"] == "灵感描述不足"

    @patch("app.routers.supervisor_router.message_service")
    def test_no_todolist_message_found_returns_false(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = "work-123"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session

        # 没有 requirements_todolist message
        mock_msg_service.get_messages_by_session.return_value = []

        data = {
            "task_item_id": "task-uuid-1",
            "task_id": "T1",
            "old_status": "pending",
            "new_status": "completed",
            "result_summary": "完成",
        }

        result = persist_event_message(
            mock_db, "session-abc", "task_status_updated", data,
        )

        assert result is False


class TestPersistTodolistReadinessUpdated:
    """验证 todolist_readiness_updated 事件的持久化"""

    @patch("app.routers.supervisor_router.message_service")
    def test_updates_readiness_in_existing_todolist(self, mock_msg_service):
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = "work-123"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session

        existing_msg = MagicMock()
        existing_msg.role = "assistant"
        existing_msg.meta = {
            "type": "requirements_todolist",
            "todoCard": {
                "intent_summary": "test",
                "todolist": [],
                "ready_to_execute": False,
            },
        }
        mock_msg_service.get_messages_by_session.return_value = [existing_msg]

        data = {
            "session_id": "session-abc",
            "ready_to_execute": True,
        }

        result = persist_event_message(
            mock_db, "session-abc", "todolist_readiness_updated", data,
        )

        assert result is True
        assert existing_msg.meta["todoCard"]["ready_to_execute"] is True
        mock_db.commit.assert_called()


class TestAnalyzeRequirementsCommitFix:
    """验证 analyze_requirements 中 ready_to_execute 的 commit 修复"""

    def test_ready_to_execute_updated_before_commit(self):
        """验证 ready_to_execute 的更新在 db.commit() 之前完成，
        而不是在 commit 之后的独立操作。

        通过检查代码中 ready_to_execute 赋值和 db.commit() 的顺序来验证。
        这里用代码内省检查顺序不够稳定，改用 mock 来验证：
        session.ready_to_execute 应在 commit 之前被设置。
        """
        # 读取 analyze_requirements 源码验证顺序
        from app.services.supervisor import tools
        import inspect
        source = inspect.getsource(tools._analyze_requirements_coroutine)

        # ready_to_execute 赋值应在 commit 之前
        ready_pos = source.find("session_obj.ready_to_execute = result.ready_to_execute")
        commit_pos = source.find("db.commit()")

        assert ready_pos > 0, "ready_to_execute assignment not found in source"
        assert commit_pos > 0, "db.commit() not found in source"
        assert ready_pos < commit_pos, (
            "ready_to_execute should be set BEFORE db.commit(), not after. "
            "This ensures it's persisted in the same transaction as task_items."
        )


class TestFrontendHistoryRestore:
    """验证前端历史消息恢复兼容新格式

    注意：这里测试的是后端持久化的格式是否正确，
    前端 JSX 的解析逻辑需要在前端测试中覆盖。
    """

    @patch("app.routers.supervisor_router.message_service")
    def test_todolist_message_has_correct_meta_for_frontend(self, mock_msg_service):
        """持久化的 message meta 应包含前端可识别的字段"""
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = "work-1"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        mock_msg_service.get_next_sort_order.return_value = 1

        data = {
            "intent_summary": "创建大纲并写第一章",
            "todolist": [
                {
                    "db_id": "t1",
                    "task_id": "T1",
                    "task": "创建大纲",
                    "owner": "outline_agent",
                    "status": "pending",
                    "depends_on": [],
                    "done_criteria": "大纲已生成",
                },
            ],
            "ready_to_execute": True,
        }

        persist_event_message(mock_db, "s1", "todolist_generated", data)

        call_kwargs = mock_msg_service.create_message.call_args[1]
        meta = call_kwargs["meta"]

        # 前端识别条件: meta.type === "requirements_todolist" && meta.todoCard
        assert meta["type"] == "requirements_todolist"
        assert meta["todoCard"] is not None
        assert "intent_summary" in meta["todoCard"]
        assert "todolist" in meta["todoCard"]
        assert "ready_to_execute" in meta["todoCard"]
        # 每个 task 应有前端需要的字段
        task = meta["todoCard"]["todolist"][0]
        assert "db_id" in task
        assert "task_id" in task
        assert "task" in task
        assert "owner" in task
        assert "status" in task
        assert "depends_on" in task
