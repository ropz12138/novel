"""Phase 3 测试：实现 Todo Execution Harness

验证：
1. serialize_task_item 正确序列化 TaskItem
2. set_task_status 原子更新任务状态并 emit 事件
3. get_next_executable_task 返回第一条 pending 且依赖已满足的任务
4. get_next_executable_task 跳过依赖未满足的任务
5. execute_todo_task 成功路径：pending -> in_progress -> completed
6. execute_todo_task 失败路径：pending -> in_progress -> failed
7. execute_todo_task 任务不存在时返回错误
8. execute_todo_task 依赖未满足时不执行
9. execute_todo_task 未知 dispatch_tool 标记 failed
10. execute_todo_task owner=user/supervisor 不自动执行
11. execute_todo_task dispatch 后 session 进入 waiting 时保持 in_progress
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch

from app.models.task_item_model import TaskItem


def _make_task(**overrides) -> TaskItem:
    defaults = dict(
        id="task-uuid-1",
        session_id="sess-1",
        task_id="T1",
        task_description="创建大纲",
        owner="outline_agent",
        status="pending",
        dispatch_tool="dispatch_outline",
        instruction="创建末日科幻故事大纲",
        sort_order=0,
    )
    defaults.update(overrides)
    return TaskItem(**defaults)


class TestSerializeTaskItem:
    """验证 serialize_task_item 序列化逻辑"""

    def test_serializes_all_required_fields(self):
        from app.services.supervisor.todo_harness import serialize_task_item
        task = _make_task()
        result = serialize_task_item(task)
        assert result["db_id"] == "task-uuid-1"
        assert result["task_id"] == "T1"
        assert result["task"] == "创建大纲"
        assert result["owner"] == "outline_agent"
        assert result["status"] == "pending"
        assert result["dispatch_tool"] == "dispatch_outline"
        assert result["instruction"] == "创建末日科幻故事大纲"

    def test_serializes_optional_fields_with_defaults(self):
        from app.services.supervisor.todo_harness import serialize_task_item
        task = _make_task()
        result = serialize_task_item(task)
        assert result["task_type"] == ""
        assert result["result_summary"] == ""
        assert result["error_message"] == ""
        assert result["depends_on"] == []


class TestSetTaskStatus:
    """验证 set_task_status 状态更新和事件发射"""

    def test_updates_status_and_commits(self):
        from app.services.supervisor.todo_harness import set_task_status
        mock_db = MagicMock()
        emitted = []
        task = _make_task()

        set_task_status(
            task=task, status="in_progress", db=mock_db,
            emit=lambda e, d: emitted.append((e, d)),
        )

        assert task.status == "in_progress"
        mock_db.commit.assert_called_once()

    def test_emits_task_status_updated_event(self):
        from app.services.supervisor.todo_harness import set_task_status
        mock_db = MagicMock()
        emitted = []
        task = _make_task()

        set_task_status(
            task=task, status="completed", db=mock_db,
            emit=lambda e, d: emitted.append((e, d)),
            result_summary="大纲已创建",
        )

        assert len(emitted) == 1
        event, data = emitted[0]
        assert event == "task_status_updated"
        assert data["task_item_id"] == "task-uuid-1"
        assert data["new_status"] == "completed"
        assert data["result_summary"] == "大纲已创建"

    def test_sets_error_message_on_failed(self):
        from app.services.supervisor.todo_harness import set_task_status
        mock_db = MagicMock()
        task = _make_task()

        set_task_status(
            task=task, status="failed", db=mock_db,
            emit=lambda e, d: None,
            error_message="灵感描述不足",
        )

        assert task.status == "failed"
        assert task.error_message == "灵感描述不足"

    def test_sets_started_at_on_in_progress(self):
        from app.services.supervisor.todo_harness import set_task_status
        mock_db = MagicMock()
        task = _make_task()
        assert task.started_at is None

        set_task_status(
            task=task, status="in_progress", db=mock_db,
            emit=lambda e, d: None,
        )

        assert task.started_at is not None

    def test_sets_completed_at_on_completed(self):
        from app.services.supervisor.todo_harness import set_task_status
        mock_db = MagicMock()
        task = _make_task()

        set_task_status(
            task=task, status="completed", db=mock_db,
            emit=lambda e, d: None,
        )

        assert task.completed_at is not None


class TestGetNextExecutableTask:
    """验证 get_next_executable_task 逻辑"""

    def test_returns_first_pending_task_with_no_dependencies(self):
        from app.services.supervisor.todo_harness import get_next_executable_task
        mock_db = MagicMock()
        task1 = _make_task(id="t1", task_id="T1", status="pending", depends_on="")
        task2 = _make_task(id="t2", task_id="T2", status="pending", depends_on="T1")
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [task1, task2]

        result = get_next_executable_task(session_id="sess-1", db=mock_db)
        assert result is not None
        assert result.id == "t1"

    def test_skips_task_with_unmet_dependency(self):
        from app.services.supervisor.todo_harness import get_next_executable_task
        mock_db = MagicMock()
        task1 = _make_task(id="t1", task_id="T1", status="pending", depends_on="")
        task2 = _make_task(id="t2", task_id="T2", status="pending", depends_on="T1")
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [task1, task2]

        # T1 still pending, so T2 depends_on T1 is not met
        # But T1 has no deps, so T1 should be returned
        result = get_next_executable_task(session_id="sess-1", db=mock_db)
        assert result.id == "t1"

    def test_returns_task_after_dependency_completed(self):
        from app.services.supervisor.todo_harness import get_next_executable_task
        mock_db = MagicMock()
        task1 = _make_task(id="t1", task_id="T1", status="completed", depends_on="")
        task2 = _make_task(id="t2", task_id="T2", status="pending", depends_on="T1")
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [task1, task2]

        result = get_next_executable_task(session_id="sess-1", db=mock_db)
        assert result is not None
        assert result.id == "t2"

    def test_returns_none_when_all_tasks_completed(self):
        from app.services.supervisor.todo_harness import get_next_executable_task
        mock_db = MagicMock()
        task1 = _make_task(id="t1", task_id="T1", status="completed", depends_on="")
        task2 = _make_task(id="t2", task_id="T2", status="completed", depends_on="T1")
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [task1, task2]

        result = get_next_executable_task(session_id="sess-1", db=mock_db)
        assert result is None

    def test_returns_none_when_no_tasks(self):
        from app.services.supervisor.todo_harness import get_next_executable_task
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = []

        result = get_next_executable_task(session_id="sess-1", db=mock_db)
        assert result is None

    def test_skips_in_progress_task(self):
        from app.services.supervisor.todo_harness import get_next_executable_task
        mock_db = MagicMock()
        task1 = _make_task(id="t1", task_id="T1", status="in_progress", depends_on="")
        task2 = _make_task(id="t2", task_id="T2", status="pending", depends_on="T1")
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.all.return_value = [task1, task2]

        # T2 depends on T1 which is in_progress (not completed), so no executable task
        result = get_next_executable_task(session_id="sess-1", db=mock_db)
        assert result is None


class TestExecuteTodoTaskSuccess:
    """验证 execute_todo_task 成功路径"""

    @pytest.mark.asyncio
    async def test_pending_to_completed_for_outline(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        emitted = []
        task = _make_task(
            owner="outline_agent",
            dispatch_tool="dispatch_outline",
            instruction="创建末日科幻故事大纲",
        )

        mock_session = MagicMock()
        mock_session.work_id = None

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.first.return_value = task
            return r

        mock_db.query.side_effect = query_side_effect

        config = {"configurable": {"db": mock_db, "emit": lambda e, d: emitted.append((e, d)), "supervisor_session_id": "sess-1"}}

        with patch(
            "app.services.supervisor.outline_agent.OutlineAgent.create_outline",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = {"work_id": "w-new", "title": "末日科幻"}
            result = await execute_todo_task(
                task_item_id="task-uuid-1", db=mock_db,
                emit=lambda e, d: emitted.append((e, d)),
                config=config,
            )

        assert "成功" in result or "completed" in result.lower() or "执行完成" in result
        assert task.status == "completed"
        mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pending_to_completed_for_chapter(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            owner="chapter_agent",
            dispatch_tool="dispatch_chapter",
            instruction="写第九章，承接第8章结尾",
        )

        mock_session = MagicMock()
        mock_session.work_id = "w1"

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.first.return_value = task
            return r

        mock_db.query.side_effect = query_side_effect

        config = {"configurable": {
            "db": mock_db,
            "emit": lambda e, d: None,
            "supervisor_session_id": "sess-1",
            "auto_mode": True,
            "sub_agent_memories": {},
        }}

        with patch("app.services.supervisor.chapter_agent.ChapterAgent.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"message": "第9章写作完成"}
            result = await execute_todo_task(
                task_item_id="task-uuid-1", db=mock_db,
                emit=lambda e, d: None,
                config=config,
            )

        assert task.status == "completed"
        mock_run.assert_awaited_once()
        kwargs = mock_run.await_args.kwargs
        assert kwargs["chapter_number"] is None
        assert "第8章结尾" in kwargs["user_message"]

    @pytest.mark.asyncio
    async def test_pending_to_completed_for_evaluation(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            owner="evaluation_agent",
            dispatch_tool="dispatch_evaluation",
            instruction="评估第1章",
        )

        mock_session = MagicMock()
        mock_session.work_id = "w1"

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.first.return_value = task
            return r

        mock_db.query.side_effect = query_side_effect

        config = {"configurable": {
            "db": mock_db,
            "emit": lambda e, d: None,
            "supervisor_session_id": "sess-1",
        }}

        with patch(
            "app.services.evaluation_agent.EvaluationAgent.evaluate_chapter",
            new_callable=AsyncMock,
        ) as mock_eval:
            mock_eval.return_value = ("第一章", "编辑评估", "读者评估", "同步评估")
            result = await execute_todo_task(
                task_item_id="task-uuid-1", db=mock_db,
                emit=lambda e, d: None,
                config=config,
            )

        assert task.status == "completed"
        mock_eval.assert_awaited_once()
        kwargs = mock_eval.await_args.kwargs
        assert kwargs["chapter_number"] is None
        assert "评估第1章" in kwargs["user_message"]

    @pytest.mark.asyncio
    async def test_evaluation_does_not_extract_wrong_chapter_number(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            owner="evaluation_agent",
            dispatch_tool="dispatch_evaluation",
            instruction="评估第9章，参考第8章结尾",
        )

        mock_session = MagicMock()
        mock_session.work_id = "w1"

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.first.return_value = task
            return r

        mock_db.query.side_effect = query_side_effect

        config = {"configurable": {
            "db": mock_db,
            "emit": lambda e, d: None,
            "supervisor_session_id": "sess-1",
        }}

        with patch(
            "app.services.evaluation_agent.EvaluationAgent.evaluate_chapter",
            new_callable=AsyncMock,
        ) as mock_eval:
            mock_eval.return_value = ("第九章", "编辑", "读者", "同步")
            await execute_todo_task(
                task_item_id="task-uuid-1", db=mock_db,
                emit=lambda e, d: None,
                config=config,
            )

        kwargs = mock_eval.await_args.kwargs
        assert kwargs["chapter_number"] is None
        assert "第8章" in kwargs["user_message"]


class TestExecuteTodoTaskFailure:
    """验证 execute_todo_task 失败路径"""

    @pytest.mark.asyncio
    async def test_dispatch_exception_marks_failed(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            owner="outline_agent",
            dispatch_tool="dispatch_outline",
        )

        mock_session = MagicMock()
        mock_session.work_id = None

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.first.return_value = task
            return r

        mock_db.query.side_effect = query_side_effect

        config = {"configurable": {
            "db": mock_db,
            "emit": lambda e, d: None,
            "supervisor_session_id": "sess-1",
        }}

        with patch(
            "app.services.supervisor.outline_agent.OutlineAgent.create_outline",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.side_effect = RuntimeError("API 调用超时")
            await execute_todo_task(
                task_item_id="task-uuid-1", db=mock_db,
                emit=lambda e, d: None,
                config=config,
            )

        assert task.status == "failed"
        assert "API 调用超时" in task.error_message

    def test_failed_dispatch_result_prefers_success_markers(self):
        """成功正文里出现“失败/不存在/请先”等词时，不应误判父任务失败。"""
        from app.services.supervisor.todo_harness import _is_failed_dispatch_result

        result_text = (
            "第6章写作完成。已同步章节元数据。\n"
            "第6章「第6章」已保存，共 3317 字。\n"
            "章节结构元数据：角色在黑暗中前进，前方等待更严酷的环境。"
        )

        assert _is_failed_dispatch_result(result_text) is False

    def test_failed_dispatch_result_detects_hard_failure_prefix(self):
        from app.services.supervisor.todo_harness import _is_failed_dispatch_result

        assert _is_failed_dispatch_result(
            "生成正文失败：目标章节已存在。第6章已有正文。"
        ) is True

    def test_structured_success_not_failed_by_message_text(self):
        """结构化 ok=true 优先，message 中出现失败类词语也不误判。"""
        from app.services.supervisor.todo_harness import (
            _is_failed_dispatch_result,
            _parse_dispatch_result,
        )

        result_text = (
            '{"ok": true, "status": "completed", "message": '
            '"第6章写作完成。章节元数据稍后可重新同步。原始日志中包含：任务执行遇到了后端错误。"}'
        )
        dispatch_result = _parse_dispatch_result(result_text)

        assert dispatch_result is not None
        assert _is_failed_dispatch_result(result_text, dispatch_result) is False

    def test_structured_failure_marks_failed(self):
        from app.services.supervisor.todo_harness import (
            _is_failed_dispatch_result,
            _parse_dispatch_result,
        )

        result_text = (
            '{"ok": false, "status": "rejected", "message": '
            '"生成正文失败：目标章节已存在。"}'
        )
        dispatch_result = _parse_dispatch_result(result_text)

        assert dispatch_result is not None
        assert _is_failed_dispatch_result(result_text, dispatch_result) is True


class TestChildTaskIdAllocation:
    def test_prefers_raw_child_task_id(self):
        from app.services.supervisor.todo_harness import _allocate_child_task_id

        used = set()
        task_id = _allocate_child_task_id(
            raw_task_id="T1",
            parent_task_id="T1",
            index=1,
            used_ids=used,
        )
        assert task_id == "T1"

    def test_fallback_and_deduplicate(self):
        from app.services.supervisor.todo_harness import _allocate_child_task_id

        used = {"T1", "T1.1"}
        task_id = _allocate_child_task_id(
            raw_task_id="T1",
            parent_task_id="T1",
            index=1,
            used_ids=used,
        )
        assert task_id == "T1.1_2"


class TestExecuteTodoTaskEdgeCases:
    """验证 execute_todo_task 边界情况"""

    @pytest.mark.asyncio
    async def test_task_not_found_returns_error(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        result = await execute_todo_task(
            task_item_id="nonexistent", db=mock_db,
            emit=lambda e, d: None,
            config={"configurable": {}},
        )

        assert "不存在" in result or "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_dependency_not_met_returns_error(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            depends_on="T99",
            status="pending",
        )

        # T99 is still pending
        dep_task = _make_task(id="t99", task_id="T99", status="pending", depends_on="")
        mock_db.query.return_value.filter_by.return_value.first.return_value = task
        # Second query for dependency check
        mock_db.query.return_value.filter_by.return_value.filter_by.return_value.first.return_value = dep_task

        result = await execute_todo_task(
            task_item_id="task-uuid-1", db=mock_db,
            emit=lambda e, d: None,
            config={"configurable": {}},
        )

        assert "依赖" in result or "dependency" in result.lower()
        assert task.status == "pending"  # Should NOT change

    @pytest.mark.asyncio
    async def test_unknown_dispatch_tool_marks_failed(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            owner="unknown_agent",
            dispatch_tool="dispatch_unknown",
        )

        mock_session = MagicMock()
        mock_session.work_id = None

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.first.return_value = task
            return r

        mock_db.query.side_effect = query_side_effect

        result = await execute_todo_task(
            task_item_id="task-uuid-1", db=mock_db,
            emit=lambda e, d: None,
            config={"configurable": {"supervisor_session_id": "sess-1"}},
        )

        assert task.status == "failed"
        assert "不可执行" in result or "unknown" in result.lower() or "无法" in result

    @pytest.mark.asyncio
    async def test_owner_user_not_auto_executable(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            owner="user",
            dispatch_tool="none",
            task_description="等待用户补充题材和基调",
            instruction="等待用户补充题材和基调",
        )
        mock_db.query.return_value.filter_by.return_value.first.return_value = task

        result = await execute_todo_task(
            task_item_id="task-uuid-1", db=mock_db,
            emit=lambda e, d: None,
            config={"configurable": {"supervisor_session_id": "sess-1"}},
        )

        # user tasks should not auto-execute
        assert task.status == "pending"  # Should NOT change
        assert "用户" in result or "user" in result.lower() or "等待" in result

    @pytest.mark.asyncio
    async def test_owner_user_with_dispatch_tool_is_executable(self):
        """planner 偶尔会误填 owner=user；只要 dispatch_tool 有效，harness 应继续执行。"""
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            owner="user",
            dispatch_tool="dispatch_outline",
            instruction="创建双人短篇小说大纲",
        )
        mock_session = MagicMock()
        mock_session.work_id = None
        mock_session.status = "completed"
        mock_session.active_child = None

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__") and model.__name__ == "SupervisorSession":
                r.filter_by.return_value.first.return_value = mock_session
            else:
                r.filter_by.return_value.first.return_value = task
            return r

        mock_db.query.side_effect = query_side_effect

        with patch(
            "app.services.supervisor.outline_agent.OutlineAgent.create_outline",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = {"work_id": "w-new", "title": "双人短篇"}
            result = await execute_todo_task(
                task_item_id=task.id, db=mock_db,
                emit=lambda e, d: None,
                config={"configurable": {"supervisor_session_id": "sess-1"}},
            )

        assert task.owner == "outline_agent"
        assert task.status == "completed"
        assert "执行完成" in result

    @pytest.mark.asyncio
    async def test_owner_supervisor_not_auto_executable(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            owner="supervisor",
            dispatch_tool="none",
            task_description="统筹后续任务",
            instruction="统筹后续任务",
        )
        mock_db.query.return_value.filter_by.return_value.first.return_value = task

        result = await execute_todo_task(
            task_item_id="task-uuid-1", db=mock_db,
            emit=lambda e, d: None,
            config={"configurable": {"supervisor_session_id": "sess-1"}},
        )

        assert task.status == "pending"

    @pytest.mark.asyncio
    async def test_waiting_session_keeps_in_progress(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            owner="outline_agent",
            dispatch_tool="dispatch_outline",
            instruction="丰富大纲",
        )

        # Simulate session going to waiting after dispatch
        mock_session = MagicMock()
        mock_session.work_id = "w1"
        mock_session.status = "waiting"
        mock_session.active_child = {"type": "edit_outline", "work_id": "w1"}

        def query_side_effect(model):
            result = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "TaskItem":
                    result.filter_by.return_value.first.return_value = task
                    return result
                elif model.__name__ == "SupervisorSession":
                    result.filter_by.return_value.first.return_value = mock_session
                    return result
            result.filter_by.return_value.first.return_value = task
            return result

        mock_db.query.side_effect = query_side_effect

        config = {"configurable": {
            "db": mock_db,
            "emit": lambda e, d: None,
            "supervisor_session_id": "sess-1",
        }}

        with patch(
            "app.services.supervisor.outline_agent.OutlineAgent.edit_outline",
            new_callable=AsyncMock,
        ) as mock_edit:
            mock_edit.return_value = {
                "message": "大纲变更已暂存",
                "outline_summary": {"total_added": 1, "total_modified": 0, "total_removed": 0},
                "character_summary": {"total_added": 0, "total_modified": 0, "total_removed": 0},
                "operations": [{"op": "add"}],
            }
            result = await execute_todo_task(
                task_item_id="task-uuid-1", db=mock_db,
                emit=lambda e, d: None,
                config=config,
            )

        assert mock_session.status == "waiting"
        assert task.status == "in_progress"
        assert "等待" in result or "waiting" in result.lower() or "确认" in result

    @pytest.mark.asyncio
    async def test_empty_dispatch_tool_uses_owner_inference(self):
        """当 dispatch_tool 为空时，根据 owner 推断"""
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(
            owner="outline_agent",
            dispatch_tool="",  # 空，需要根据 owner 推断
        )

        mock_session = MagicMock()
        mock_session.work_id = None

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.first.return_value = task
            return r

        mock_db.query.side_effect = query_side_effect

        config = {"configurable": {
            "db": mock_db,
            "emit": lambda e, d: None,
            "supervisor_session_id": "sess-1",
        }}

        with patch(
            "app.services.supervisor.outline_agent.OutlineAgent.create_outline",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = {"work_id": "w-new", "title": "大纲"}
            result = await execute_todo_task(
                task_item_id="task-uuid-1", db=mock_db,
                emit=lambda e, d: None,
                config=config,
            )

        assert task.status == "completed"
        mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_already_in_progress_returns_warning(self):
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()
        task = _make_task(status="in_progress")
        mock_db.query.return_value.filter_by.return_value.first.return_value = task

        result = await execute_todo_task(
            task_item_id="task-uuid-1", db=mock_db,
            emit=lambda e, d: None,
            config={"configurable": {}},
        )

        assert "进行中" in result or "in_progress" in result.lower() or "已在执行" in result
