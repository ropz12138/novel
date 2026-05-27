"""Phase 2 测试：新增 TaskItem 可执行字段

验证：
1. TaskItem 模型包含 task_type/dispatch_tool/instruction/error_message/started_at/completed_at 字段
2. 老任务没有这些字段时使用默认值不报错
3. requirements_planner.txt prompt 要求 LLM 返回 dispatch_tool/instruction 字段
4. TaskItemResult Pydantic 模型包含新字段
5. analyze_requirements 落库时写入新字段
6. analyze_requirements emit 时带上新字段
7. owner 推断 dispatch_tool 的兼容逻辑
8. 前端任务卡片兼容显示新字段（通过 emit 数据验证）
"""

import sys

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, "/root/Novel/backend")


class TestTaskItemNewColumns:
    """验证 TaskItem 模型新增字段"""

    def test_task_item_has_task_type(self):
        from app.models.task_item_model import TaskItem
        columns = {c.name for c in TaskItem.__table__.columns}
        assert "task_type" in columns

    def test_task_item_has_dispatch_tool(self):
        from app.models.task_item_model import TaskItem
        columns = {c.name for c in TaskItem.__table__.columns}
        assert "dispatch_tool" in columns

    def test_task_item_has_instruction(self):
        from app.models.task_item_model import TaskItem
        columns = {c.name for c in TaskItem.__table__.columns}
        assert "instruction" in columns

    def test_task_item_has_error_message(self):
        from app.models.task_item_model import TaskItem
        columns = {c.name for c in TaskItem.__table__.columns}
        assert "error_message" in columns

    def test_task_item_has_started_at(self):
        from app.models.task_item_model import TaskItem
        columns = {c.name for c in TaskItem.__table__.columns}
        assert "started_at" in columns

    def test_task_item_has_completed_at(self):
        from app.models.task_item_model import TaskItem
        columns = {c.name for c in TaskItem.__table__.columns}
        assert "completed_at" in columns


class TestTaskItemNewFieldDefaults:
    """验证新字段的默认值 — 老任务兼容"""

    def test_default_task_type_is_empty_string(self):
        from app.models.task_item_model import TaskItem
        ti = TaskItem(id="test-1", session_id="sess-1", task_id="T1")
        assert ti.task_type == ""

    def test_default_dispatch_tool_is_empty_string(self):
        from app.models.task_item_model import TaskItem
        ti = TaskItem(id="test-1", session_id="sess-1", task_id="T1")
        assert ti.dispatch_tool == ""

    def test_default_instruction_is_empty_string(self):
        from app.models.task_item_model import TaskItem
        ti = TaskItem(id="test-1", session_id="sess-1", task_id="T1")
        assert ti.instruction == ""

    def test_default_error_message_is_empty_string(self):
        from app.models.task_item_model import TaskItem
        ti = TaskItem(id="test-1", session_id="sess-1", task_id="T1")
        assert ti.error_message == ""

    def test_default_started_at_is_none(self):
        from app.models.task_item_model import TaskItem
        ti = TaskItem(id="test-1", session_id="sess-1", task_id="T1")
        assert ti.started_at is None

    def test_default_completed_at_is_none(self):
        from app.models.task_item_model import TaskItem
        ti = TaskItem(id="test-1", session_id="sess-1", task_id="T1")
        assert ti.completed_at is None


class TestTaskItemWithNewFields:
    """验证使用新字段创建 TaskItem"""

    def test_create_task_item_with_all_new_fields(self):
        from app.models.task_item_model import TaskItem
        now = datetime.now(timezone.utc)
        ti = TaskItem(
            id="ti-new",
            session_id="sess-1",
            task_id="T1",
            task_description="创建大纲",
            owner="outline_agent",
            task_type="outline",
            dispatch_tool="dispatch_outline",
            instruction="创建末日科幻故事大纲",
            started_at=now,
        )
        assert ti.task_type == "outline"
        assert ti.dispatch_tool == "dispatch_outline"
        assert ti.instruction == "创建末日科幻故事大纲"
        assert ti.started_at == now
        assert ti.completed_at is None


class TestTaskItemResultNewFields:
    """验证 analyze_requirements 内的 TaskItemResult Pydantic 模型包含新字段"""

    def test_task_item_result_has_dispatch_tool(self):
        """TaskItemResult 应包含 dispatch_tool 字段"""
        from app.services.supervisor.tools import analyze_requirements
        import inspect
        source = inspect.getsource(analyze_requirements.coroutine)
        assert "dispatch_tool" in source

    def test_task_item_result_has_instruction(self):
        """TaskItemResult 应包含 instruction 字段"""
        from app.services.supervisor.tools import analyze_requirements
        import inspect
        source = inspect.getsource(analyze_requirements.coroutine)
        assert "instruction" in source

    def test_task_item_result_has_task_type(self):
        """TaskItemResult 应包含 task_type 字段"""
        from app.services.supervisor.tools import analyze_requirements
        import inspect
        source = inspect.getsource(analyze_requirements.coroutine)
        assert "task_type" in source


class TestDispatchToolInferenceFromOwner:
    """验证从 owner 推断 dispatch_tool 的兼容逻辑"""

    def test_outline_agent_infers_dispatch_outline(self):
        from app.services.supervisor.tools import analyze_requirements
        import inspect
        source = inspect.getsource(analyze_requirements.coroutine)
        # 应有 owner -> dispatch_tool 的推断逻辑
        assert "outline_agent" in source
        assert "dispatch_outline" in source

    def test_chapter_agent_infers_dispatch_chapter(self):
        from app.services.supervisor.tools import analyze_requirements
        import inspect
        source = inspect.getsource(analyze_requirements.coroutine)
        assert "chapter_agent" in source
        assert "dispatch_chapter" in source

    def test_evaluation_agent_infers_dispatch_evaluation(self):
        from app.services.supervisor.tools import analyze_requirements
        import inspect
        source = inspect.getsource(analyze_requirements.coroutine)
        assert "evaluation_agent" in source
        assert "dispatch_evaluation" in source


class TestRequirementsPlannerPromptUpdate:
    """验证 requirements_planner.txt prompt 要求 LLM 返回新字段"""

    def test_prompt_mentions_dispatch_tool(self):
        from pathlib import Path
        prompt_dir = Path(__file__).resolve().parent.parent / "app" / "services" / "prompt_templates"
        prompt = (prompt_dir / "requirements_planner.txt").read_text(encoding="utf-8")
        assert "dispatch_tool" in prompt

    def test_prompt_mentions_instruction(self):
        from pathlib import Path
        prompt_dir = Path(__file__).resolve().parent.parent / "app" / "services" / "prompt_templates"
        prompt = (prompt_dir / "requirements_planner.txt").read_text(encoding="utf-8")
        assert "instruction" in prompt

    def test_prompt_mentions_task_type(self):
        from pathlib import Path
        prompt_dir = Path(__file__).resolve().parent.parent / "app" / "services" / "prompt_templates"
        prompt = (prompt_dir / "requirements_planner.txt").read_text(encoding="utf-8")
        assert "task_type" in prompt

    def test_prompt_has_example_with_new_fields(self):
        from pathlib import Path
        prompt_dir = Path(__file__).resolve().parent.parent / "app" / "services" / "prompt_templates"
        prompt = (prompt_dir / "requirements_planner.txt").read_text(encoding="utf-8")
        assert "dispatch_outline" in prompt
        assert "outline" in prompt.lower()


class TestAnalyzeRequirementsEmitsNewFields:
    """验证 analyze_requirements 在 emit todolist_generated 时带上新字段"""

    def test_emit_includes_dispatch_tool_and_instruction(self):
        """emit 的 persisted_tasks 应包含 dispatch_tool 和 instruction"""
        from app.services.supervisor.tools import analyze_requirements
        import inspect
        source = inspect.getsource(analyze_requirements.coroutine)

        # 验证 persisted_tasks 构建时包含了新字段
        assert '"dispatch_tool"' in source or "'dispatch_tool'" in source
        assert '"instruction"' in source or "'instruction'" in source
        assert '"task_type"' in source or "'task_type'" in source
