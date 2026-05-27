"""测试重构后的 supervisor 工具注册

验证：
1. ALL_TOOLS 包含所有预期的工具（20个）
2. dispatch_requirements_planner 已移除
3. 新增工具已注册：analyze_requirements, read_work_context, read_chat_history, update_task_status
4. 补充的子 Agent 查询工具已注册
5. 原有查询和派发工具保持不变
"""

import sys

import pytest

sys.path.insert(0, "/root/Novel/backend")


class TestToolsRegistration:
    """验证重构后的 ALL_TOOLS 注册"""

    EXPECTED_QUERY_TOOLS = {
        "query_characters",
        "query_chapters",
        "query_chapter_meta",
        "grep_chapter_meta",
        "grep",
        "read_outline",
        "query_outline_related_chapters",
        "read_chapter",
        "query_characters_by_chapter",
        "grep_in_chapter",
        "query_chapter_outline",
        "query_previous_chapters",
        "query_foreshadowing",
        "read_work_context",
        "read_chat_history",
    }

    EXPECTED_ANALYSIS_TOOLS = {
        "analyze_requirements",
        "update_task_status",
        "update_todolist_readiness",
    }

    REMOVED_TOOLS = {
        "dispatch_requirements_planner",
        "dispatch_outline",
        "dispatch_chapter",
        "dispatch_evaluation",
    }

    def _get_tool_names(self):
        from app.services.supervisor.tools import ALL_TOOLS
        return {t.name for t in ALL_TOOLS}

    def test_all_tools_count(self):
        """应该恰好注册 20 个工具（不含 dispatch_*）"""
        from app.services.supervisor.tools import ALL_TOOLS
        assert len(ALL_TOOLS) == 21

    def test_tool_names_unique(self):
        """所有工具名不应重复"""
        from app.services.supervisor.tools import ALL_TOOLS
        names = [t.name for t in ALL_TOOLS]
        assert len(names) == len(set(names))

    def test_query_tools_registered(self):
        """15 个查询工具应全部注册"""
        names = self._get_tool_names()
        for tool_name in self.EXPECTED_QUERY_TOOLS:
            assert tool_name in names, f"查询工具 {tool_name} 未注册"

    def test_analysis_tools_registered(self):
        """需求分析 + 状态机工具应注册"""
        names = self._get_tool_names()
        for tool_name in self.EXPECTED_ANALYSIS_TOOLS:
            assert tool_name in names, f"分析工具 {tool_name} 未注册"

    def test_dispatch_tools_removed_from_supervisor(self):
        """dispatch_* 入口工具已从 Supervisor 移除"""
        names = self._get_tool_names()
        for tool_name in ("dispatch_outline", "dispatch_chapter", "dispatch_evaluation"):
            assert tool_name not in names, f"派发工具 {tool_name} 仍暴露在 ALL_TOOLS"

    def test_dispatch_requirements_planner_removed(self):
        """dispatch_requirements_planner 应已移除"""
        names = self._get_tool_names()
        for tool_name in self.REMOVED_TOOLS:
            assert tool_name not in names, f"已移除的工具 {tool_name} 仍存在"

    def test_analyze_requirements_is_async(self):
        """analyze_requirements 应有 coroutine（异步工具）"""
        from app.services.supervisor.tools import analyze_requirements
        assert analyze_requirements.coroutine is not None

    def test_update_task_status_is_sync(self):
        """update_task_status 应有 func（同步工具）"""
        from app.services.supervisor.tools import update_task_status
        assert update_task_status.func is not None

    def test_read_work_context_is_sync(self):
        """read_work_context 应有 func（同步工具）"""
        from app.services.supervisor.tools import read_work_context
        assert read_work_context.func is not None

    def test_read_chat_history_is_sync(self):
        """read_chat_history 应有 func（同步工具）"""
        from app.services.supervisor.tools import read_chat_history
        assert read_chat_history.func is not None


class TestUpdateTaskStatusTool:
    """验证 update_task_status 工具的行为"""

    def test_update_task_status_schema(self):
        from app.services.supervisor.tools import UpdateTaskStatusInput
        schema = UpdateTaskStatusInput.model_json_schema()
        props = schema["properties"]
        assert "task_item_id" in props
        assert "status" in props
        assert "result_summary" in props
        required = schema.get("required", [])
        assert "task_item_id" in required
        assert "status" in required

    def test_update_task_status_rejects_invalid_status(self):
        """不合法的状态应在工具函数层面被拒绝"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_task_status

        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_task.status = "pending"
        mock_task.task_id = "T1"
        mock_task.task_description = "测试任务"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_task

        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}

        result = update_task_status.func(
            task_item_id="ti-1", status="invalid_status", result_summary="", config=config,
        )
        assert "无效状态" in result

    def test_update_task_status_accepts_valid_statuses(self):
        from app.services.supervisor.tools import UpdateTaskStatusInput
        for s in ["pending", "in_progress", "completed", "skipped", "failed"]:
            inp = UpdateTaskStatusInput(task_item_id="ti-1", status=s)
            assert inp.status == s

    def test_update_task_status_returns_not_found(self):
        """不存在的 task_item_id 应返回未找到"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_task_status

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}

        result = update_task_status.func(
            task_item_id="nonexistent", status="completed", result_summary="", config=config,
        )
        assert "不存在" in result or "未找到" in result

    def test_update_task_status_updates_db(self):
        """存在的 task_item 应被更新"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_task_status

        mock_task = MagicMock()
        mock_task.status = "pending"
        mock_task.task_id = "T1"
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_task

        emitted = []

        def capture_emit(event, data):
            emitted.append((event, data))

        config = {"configurable": {"db": mock_db, "emit": capture_emit}}

        result = update_task_status.func(
            task_item_id="ti-1",
            status="completed",
            result_summary="大纲已创建",
            config=config,
        )

        assert mock_task.status == "completed"
        assert mock_task.result_summary == "大纲已创建"
        mock_db.commit.assert_called()
        assert any(e[0] == "task_status_updated" for e in emitted)

    def test_update_task_status_rejects_reopening_terminal_task(self):
        """终态任务不应被 LLM 重开或改跳过，以免绕过失败任务继续执行。"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_task_status

        mock_task = MagicMock()
        mock_task.status = "failed"
        mock_task.task_id = "T1"
        mock_task.task_description = "撰写第二章正文"
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_task

        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}

        result = update_task_status.func(
            task_item_id="ti-1",
            status="pending",
            result_summary="重试",
            config=config,
        )

        assert "不可改为 pending" in result
        assert mock_task.status == "failed"
        mock_db.commit.assert_not_called()


class TestAnalyzeRequirementsTool:
    """验证 analyze_requirements 工具的 schema"""

    def test_analyze_requirements_schema(self):
        from app.services.supervisor.tools import AnalyzeRequirementsInput
        schema = AnalyzeRequirementsInput.model_json_schema()
        props = schema["properties"]
        assert "message" in props
        assert "work_context" in props
        assert "history" in props
        required = schema.get("required", [])
        assert "message" in required


class TestUpdateTodolistReadinessTool:
    """验证 update_todolist_readiness 工具"""

    def test_update_todolist_readiness_schema(self):
        from app.services.supervisor.tools import UpdateTodolistReadinessInput
        schema = UpdateTodolistReadinessInput.model_json_schema()
        props = schema["properties"]
        assert "session_id" not in props
        assert "ready_to_execute" in props
        required = schema.get("required", [])
        assert "ready_to_execute" in required

    def test_update_todolist_readiness_returns_not_found(self):
        """不存在的程序注入 session_id 应返回未找到"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_todolist_readiness

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None, "supervisor_session_id": "nonexistent"}}

        result = update_todolist_readiness.func(
            ready_to_execute=True, config=config,
        )
        assert "不存在" in result

    def test_update_todolist_readiness_emits_event(self):
        """更新成功后应 emit todolist_readiness_updated 事件"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_todolist_readiness

        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session

        emitted = []

        def capture_emit(event, data):
            emitted.append((event, data))

        config = {"configurable": {"db": mock_db, "emit": capture_emit, "supervisor_session_id": "sess-1"}}

        result = update_todolist_readiness.func(
            ready_to_execute=True, config=config,
        )

        mock_db.commit.assert_called()
        assert any(e[0] == "todolist_readiness_updated" for e in emitted)
        readiness_event = [e for e in emitted if e[0] == "todolist_readiness_updated"][0]
        assert readiness_event[1]["ready_to_execute"] is True
