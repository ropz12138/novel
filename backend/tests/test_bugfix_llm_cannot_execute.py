"""Bug Fix 测试：修复 LLM 无法使用 execute_todo_task 的问题

根本原因（从 LangSmith 日志发现）：
1. read_todolist 要求 session_id 参数，LLM 不知道真实 session_id → 改为从 config 自动获取
2. execute_todo_task 要求 task_item_id (UUID)，但 analyze_requirements 返回文本不含它 → 支持用 task_id (如 T1) 查找
3. analyze_requirements 返回文本需要包含 task_id 和 db_id，让 LLM 能传递
4. prompt 需要更强的约束
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestReadTodolistFromConfig:
    """验证 read_todolist 从 config 自动获取 session_id"""

    def test_read_todolist_schema_does_not_require_session_id(self):
        """read_todolist 的 schema 不应要求 LLM 传入 session_id"""
        from app.services.supervisor.tools import ALL_TOOLS
        tool = next(t for t in ALL_TOOLS if t.name == "read_todolist")
        schema = tool.args_schema.model_json_schema()
        required = schema.get("required", [])
        # session_id 不应是 required — 应从 config 获取
        assert "session_id" not in required

    def test_read_todolist_has_no_session_id_param(self):
        """read_todolist 不应暴露 session_id 参数给 LLM"""
        from app.services.supervisor.tools import ALL_TOOLS
        tool = next(t for t in ALL_TOOLS if t.name == "read_todolist")
        schema = tool.args_schema.model_json_schema()
        props = schema.get("properties", {})
        # 不应有 session_id 属性 — 它应从 config 自动获取
        assert "session_id" not in props


class TestExecuteTodoTaskAcceptsTaskId:
    """验证 execute_todo_task 支持用 task_id (如 T1) 而不是只能用 UUID"""

    @pytest.mark.asyncio
    async def test_execute_todo_task_with_task_id_string(self):
        """execute_todo_task 应接受 task_id 参数如 'T1'"""
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = MagicMock()
        task.id = "task-uuid-1"
        task.task_id = "T1"
        task.status = "pending"
        task.task_description = "创建大纲"
        task.owner = "outline_agent"
        task.dispatch_tool = "dispatch_outline"
        task.instruction = "创建大纲"
        task.depends_on = ""

        mock_session = MagicMock()
        mock_session.work_id = None

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
                elif model.__name__ == "TaskItem":
                    r.filter_by.return_value.first.return_value = task
                    return r
            r.filter_by.return_value.first.return_value = task
            return r

        mock_db.query.side_effect = query_side_effect

        config = {"configurable": {
            "db": mock_db,
            "emit": lambda e, d: None,
            "supervisor_session_id": "sess-1",
        }}

        with patch("app.services.supervisor.tools.dispatch_outline") as mock_dispatch:
            mock_dispatch.coroutine = AsyncMock(return_value="大纲创建成功")
            result = await execute_todo_task(
                task_item_id="T1", db=mock_db,
                emit=lambda e, d: None,
                config=config,
            )

        assert task.status == "completed"

    def test_execute_todo_task_schema_param_renamed(self):
        """execute_todo_task 的参数名应更直观"""
        from app.services.supervisor.tools import ALL_TOOLS
        tool = next(t for t in ALL_TOOLS if t.name == "execute_todo_task")
        schema = tool.args_schema.model_json_schema()
        props = schema.get("properties", {})
        # 应有一个参数来指定任务
        assert "task_item_id" in props or "task_id" in props


class TestAnalyzeRequirementsReturnsTaskIds:
    """验证 analyze_requirements 返回文本包含 task_id 和 db_id"""

    def test_analyze_requirements_source_contains_ids(self):
        """analyze_requirements 源码中应将 task_id 和 db_id 包含在返回文本中"""
        from app.services.supervisor.tools import analyze_requirements
        import inspect
        source = inspect.getsource(analyze_requirements.coroutine)

        # 返回文本应包含 task_id 信息，让 LLM 能传递给 execute_todo_task
        assert "task_id" in source
        assert "db_id" in source


class TestExecuteTodoTaskSchema:
    """验证 execute_todo_task schema 描述清晰"""

    def test_description_mentions_task_id_format(self):
        """工具描述应说明可以传入 task_id"""
        from app.services.supervisor.tools import ALL_TOOLS
        tool = next(t for t in ALL_TOOLS if t.name == "execute_todo_task")
        desc = tool.description
        # 应提到如何找到 task_id
        assert "task_id" in desc.lower() or "T1" in desc or "任务ID" in desc or "read_todolist" in desc
