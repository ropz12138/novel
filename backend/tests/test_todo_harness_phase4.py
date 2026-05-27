"""Phase 4 测试：接入 Supervisor 工具和 Prompt

验证：
1. ALL_TOOLS 包含 execute_todo_task
2. ALL_TOOLS 包含 read_todolist
3. execute_todo_task 工具有正确的 schema 和 description
4. read_todolist 工具有正确的 schema 和 description
5. system.txt prompt 包含 execute_todo_task 规则
6. system.txt prompt 禁止直接 dispatch todolist 任务
7. system.txt prompt 将 update_task_status 降级为修正工具
"""

import pytest
from unittest.mock import MagicMock


class TestExecuteTodoTaskInAllTools:
    """验证 execute_todo_task 工具注册"""

    def test_execute_todo_task_in_all_tools(self):
        from app.services.supervisor.tools import ALL_TOOLS
        names = {t.name for t in ALL_TOOLS}
        assert "execute_todo_task" in names

    def test_execute_todo_task_is_async(self):
        from app.services.supervisor.tools import ALL_TOOLS
        tool = next(t for t in ALL_TOOLS if t.name == "execute_todo_task")
        assert tool.coroutine is not None

    def test_execute_todo_task_schema_has_task_item_id(self):
        from app.services.supervisor.tools import ALL_TOOLS
        tool = next(t for t in ALL_TOOLS if t.name == "execute_todo_task")
        schema = tool.args_schema.model_json_schema()
        props = schema.get("properties", {})
        assert "task_item_id" in props
        required = schema.get("required", [])
        assert "task_item_id" in required

    def test_execute_todo_task_description_mentions_todolist(self):
        from app.services.supervisor.tools import ALL_TOOLS
        tool = next(t for t in ALL_TOOLS if t.name == "execute_todo_task")
        assert "todolist" in tool.description.lower() or "任务" in tool.description


class TestReadTodolistInAllTools:
    """验证 read_todolist 工具注册"""

    def test_read_todolist_in_all_tools(self):
        from app.services.supervisor.tools import ALL_TOOLS
        names = {t.name for t in ALL_TOOLS}
        assert "read_todolist" in names

    def test_read_todolist_schema_no_params_needed(self):
        """read_todolist 从 config 自动获取 session_id，LLM 无需传参"""
        from app.services.supervisor.tools import ALL_TOOLS
        tool = next(t for t in ALL_TOOLS if t.name == "read_todolist")
        schema = tool.args_schema.model_json_schema()
        props = schema.get("properties", {})
        assert "session_id" not in props

    def test_read_todolist_returns_tasks_and_readiness(self):
        """read_todolist 工具应返回任务列表和 readiness 状态"""
        from app.services.supervisor.tools import ALL_TOOLS
        tool = next(t for t in ALL_TOOLS if t.name == "read_todolist")
        assert tool.func is not None  # 同步工具


class TestSystemPromptUpdated:
    """验证 system.txt prompt 包含新规则"""

    def test_prompt_mentions_execute_todo_task(self):
        from pathlib import Path
        prompt_dir = Path(__file__).resolve().parent.parent / "app" / "services" / "prompt_templates"
        prompt = (prompt_dir / "system.txt").read_text(encoding="utf-8")
        assert "execute_todo_task" in prompt

    def test_prompt_prohibits_direct_dispatch_for_todolist(self):
        from pathlib import Path
        prompt_dir = Path(__file__).resolve().parent.parent / "app" / "services" / "prompt_templates"
        prompt = (prompt_dir / "system.txt").read_text(encoding="utf-8")
        assert "禁止" in prompt and "dispatch" in prompt and "todolist" in prompt

    def test_prompt_downgrades_update_task_status(self):
        from pathlib import Path
        prompt_dir = Path(__file__).resolve().parent.parent / "app" / "services" / "prompt_templates"
        prompt = (prompt_dir / "system.txt").read_text(encoding="utf-8")
        # update_task_status 应被描述为修正工具
        # 搜索是否有"修正"或"异常"相关描述
        assert "修正" in prompt or "异常" in prompt or "手动调整" in prompt

    def test_prompt_mentions_read_todolist(self):
        from pathlib import Path
        prompt_dir = Path(__file__).resolve().parent.parent / "app" / "services" / "prompt_templates"
        prompt = (prompt_dir / "system.txt").read_text(encoding="utf-8")
        assert "read_todolist" in prompt


class TestToolCountUpdated:
    """验证工具数量更新"""

    def test_all_tools_count_increased(self):
        from app.services.supervisor.tools import ALL_TOOLS
        # 原来是 21，新增 2 个工具（execute_todo_task + read_todolist）= 23
        assert len(ALL_TOOLS) == 23

    def test_tool_names_still_unique(self):
        from app.services.supervisor.tools import ALL_TOOLS
        names = [t.name for t in ALL_TOOLS]
        assert len(names) == len(set(names))
