"""测试：analyze_requirements 重复调用时清理旧 todolist

验证：
1. analyze_requirements 首次调用正常创建任务
2. analyze_requirements 重复调用时清理旧任务后再创建新任务
3. execute_todo_task 依赖检查在重复 task_id 场景下正确选择 completed 状态
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.models.task_item_model import TaskItem


def _make_task(**overrides) -> TaskItem:
    defaults = dict(
        id="task-uuid-1",
        session_id="sess-1",
        parent_id=None,
        depth=0,
        agent_scope="supervisor",
        task_id="T1",
        task_description="创建大纲",
        owner="outline_agent",
        status="pending",
        dispatch_tool="dispatch_outline",
        instruction="创建末日科幻故事大纲",
        sort_order=0,
        depends_on="",
        done_criteria="",
        task_type="",
    )
    defaults.update(overrides)
    return TaskItem(**defaults)


class TestAnalyzeRequirementsCleanupOldTodolist:
    """验证 analyze_requirements 在创建新 todolist 前清理旧任务"""

    @pytest.mark.asyncio
    async def test_second_call_deletes_old_parent_and_child_tasks(self):
        """重复调用时：先删除旧的父任务和子任务，再创建新任务"""
        from app.services.supervisor.todo_harness import cleanup_session_todolist

        mock_db = MagicMock()

        old_parent1 = _make_task(id="old-p1", task_id="T1", depth=0, parent_id=None)
        old_parent2 = _make_task(id="old-p2", task_id="T2", depth=0, parent_id=None)
        old_child1 = _make_task(
            id="old-c1", task_id="T1.1", depth=1,
            parent_id="old-p1", agent_scope="chapter_agent",
        )
        old_child2 = _make_task(
            id="old-c2", task_id="T1.2", depth=1,
            parent_id="old-p1", agent_scope="chapter_agent",
        )

        # cleanup_session_todolist 的调用序列：
        # 1. query(TaskItem).filter_by(session_id=).filter(depth/parent).all() -> [parent1, parent2]
        # 2. query(TaskItem).filter_by(session_id=, parent_id=parent1.id).all() -> [child1, child2]
        # 3. query(TaskItem).filter_by(session_id=, parent_id=parent2.id).all() -> []

        # 使用 side_effect 让每次 query 返回不同的 mock 链
        parent_query = MagicMock()
        parent_query.filter_by.return_value.filter.return_value.all.return_value = [
            old_parent1, old_parent2,
        ]

        child_query_p1 = MagicMock()
        child_query_p1.filter_by.return_value.all.return_value = [old_child1, old_child2]

        child_query_p2 = MagicMock()
        child_query_p2.filter_by.return_value.all.return_value = []

        query_sequence = [parent_query, child_query_p1, child_query_p2]
        query_index = [0]

        def mock_query(model):
            idx = query_index[0]
            query_index[0] += 1
            if idx < len(query_sequence):
                return query_sequence[idx]
            return MagicMock()

        mock_db.query.side_effect = mock_query

        cleanup_session_todolist(session_id="sess-1", db=mock_db)

        # 验证：所有旧任务（父任务和子任务）都应该被 delete
        deleted_ids = [call.args[0].id for call in mock_db.delete.call_args_list]
        assert "old-p1" in deleted_ids
        assert "old-p2" in deleted_ids
        assert "old-c1" in deleted_ids
        assert "old-c2" in deleted_ids

        # 验证：commit 被调用
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_no_tasks_does_not_crash(self):
        """当 session 中没有旧任务时，清理函数不报错"""
        from app.services.supervisor.todo_harness import cleanup_session_todolist

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.filter.return_value.all.return_value = []

        # 不应报错
        cleanup_session_todolist(session_id="sess-1", db=mock_db)

        # 不应调用 delete
        mock_db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_handles_rollback_on_error(self):
        """清理过程中如果 commit 失败，应 rollback"""
        from app.services.supervisor.todo_harness import cleanup_session_todolist

        mock_db = MagicMock()
        old_task = _make_task(id="old-1", task_id="T1", depth=0, parent_id=None)
        mock_db.query.return_value.filter_by.return_value.filter.return_value.all.side_effect = [
            [old_task],  # 父任务
            [],           # 子任务
        ]
        mock_db.commit.side_effect = RuntimeError("DB error")

        with pytest.raises(RuntimeError):
            cleanup_session_todolist(session_id="sess-1", db=mock_db)

        mock_db.rollback.assert_called_once()


class TestExecuteTodoTaskDependencyWithDuplicateTaskIds:
    """验证 execute_todo_task 在存在重复 task_id 时的依赖检查行为"""

    @pytest.mark.asyncio
    async def test_dependency_check_with_duplicate_task_ids_picks_completed(self):
        """当同一 session 中有两条 task_id=T1 的记录，一条 completed 一条 pending 时，
        dep_map 应选择 completed 状态，使 T2 能够执行。"""
        from app.services.supervisor.todo_harness import execute_todo_task

        mock_db = MagicMock()

        # T2 依赖 T1
        task_t2 = _make_task(
            id="t2-uuid",
            task_id="T2",
            status="pending",
            depends_on="T1",
            owner="evaluation_agent",
            dispatch_tool="dispatch_evaluation",
            instruction="评估第一章",
        )

        # 两个 T1：一个是 completed，一个是 pending
        t1_completed = _make_task(
            id="t1-old-uuid",
            task_id="T1",
            status="completed",
            depends_on="",
        )
        t1_pending = _make_task(
            id="t1-new-uuid",
            task_id="T1",
            status="pending",
            depends_on="",
        )

        mock_session = MagicMock()
        mock_session.work_id = "w1"
        mock_session.status = "completed"
        mock_session.active_child = None

        call_count = [0]
        def query_side_effect(model):
            call_count[0] += 1
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "TaskItem":
                    if call_count[0] == 1:
                        # resolve_task_identifier
                        r.filter_by.return_value.first.return_value = task_t2
                    else:
                        # 依赖检查：返回两个 T1
                        r.filter_by.return_value.filter.return_value.all.return_value = [
                            t1_completed, t1_pending,
                        ]
                    return r
                elif model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.first.return_value = task_t2
            return r

        mock_db.query.side_effect = query_side_effect

        config = {"configurable": {
            "db": mock_db,
            "emit": lambda e, d: None,
            "supervisor_session_id": "sess-1",
            "enable_evaluation": True,
        }}

        with patch(
            "app.services.evaluation_agent.EvaluationAgent.evaluate_chapter",
            new_callable=AsyncMock,
        ) as mock_eval:
            mock_eval.return_value = ("第一章", "编辑", "读者", "同步")
            result = await execute_todo_task(
                task_item_id="t2-uuid", db=mock_db,
                emit=lambda e, d: None,
                config=config,
            )

        # T2 应该能够执行，因为 dep_map 中 T1 是 completed
        assert task_t2.status == "completed"
        assert "执行完成" in result
