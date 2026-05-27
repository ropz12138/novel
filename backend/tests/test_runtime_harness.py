"""Phase 7-12 测试：Runtime Harness 完整化

验证：
Phase 7 - Run Lifecycle Harness:
1. before_run 生成 run_id 并构建 SupervisorRunContext
2. after_run 执行 reconciliation 并持久化事件
3. on_error 标记 session error 并执行 reconciliation

Phase 8 - Context Harness:
4. build_supervisor_runtime_context 包含 session/work/todolist 摘要
5. context 包含下一条可执行任务信息

Phase 9 - Tool Policy Harness:
6. validate_tool_call_policy 检测直接 dispatch todolist 任务
7. execute_todo_task bypass 时不触发 warning

Phase 10 - Child Agent Harness:
8. set_active_child 统一写入 task_item_id
9. clear_active_child 清理状态

Phase 11 - Recovery Harness:
10. recover_session_on_resume 修复中断状态
11. in_progress 任务在无 active_child 时回退

Phase 12 - Observability Harness:
12. log_run_event 持久化运行事件
13. 事件包含 run_id / event_type / payload
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

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


# ── Phase 7: Run Lifecycle Harness ──


class TestRunLifecycleHarness:
    """验证 SupervisorRuntimeHarness 生命周期"""

    def test_before_run_generates_run_context(self):
        from app.services.supervisor.runtime_harness import SupervisorRuntimeHarness

        harness = SupervisorRuntimeHarness()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.work_id = "w1"
        mock_session.status = "running"
        mock_session.ready_to_execute = True

        ctx = harness.before_run(session=mock_session, user_message="写一个故事")

        assert ctx["run_id"] is not None
        assert len(ctx["run_id"]) > 0
        assert ctx["session_id"] == "sess-1"
        assert ctx["work_id"] == "w1"
        assert ctx["user_message"] == "写一个故事"
        assert ctx["ready_to_execute"] is True

    def test_after_run_calls_reconciliation(self):
        from app.services.supervisor.runtime_harness import SupervisorRuntimeHarness

        harness = SupervisorRuntimeHarness()
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"

        emitted = []

        harness.after_run(
            session=mock_session,
            run_ctx={"run_id": "run-1", "session_id": "sess-1"},
            db=mock_db,
            emit=lambda e, d: emitted.append((e, d)),
        )

        # after_run 应该执行 reconciliation
        run_completed_events = [(e, d) for e, d in emitted if e == "run_completed"]
        assert len(run_completed_events) == 1

    def test_on_error_marks_session_error(self):
        from app.services.supervisor.runtime_harness import SupervisorRuntimeHarness

        harness = SupervisorRuntimeHarness()
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"

        emitted = []

        harness.on_error(
            session=mock_session,
            run_ctx={"run_id": "run-1", "session_id": "sess-1"},
            exc=RuntimeError("test error"),
            db=mock_db,
            emit=lambda e, d: emitted.append((e, d)),
        )

        run_failed_events = [(e, d) for e, d in emitted if e == "run_failed"]
        assert len(run_failed_events) == 1


# ── Phase 8: Context Harness ──


class TestContextHarness:
    """验证 build_supervisor_runtime_context"""

    def test_builds_context_with_todolist_summary(self):
        from app.services.supervisor.runtime_harness import build_supervisor_runtime_context

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.work_id = "w1"
        mock_session.status = "running"
        mock_session.ready_to_execute = True
        mock_session.active_child = None

        task1 = _make_task(id="t1", task_id="T1", status="completed")
        task2 = _make_task(id="t2", task_id="T2", status="pending")

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "TaskItem":
                    r.filter_by.return_value.order_by.return_value.all.return_value = [task1, task2]
                    return r
                elif model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
                elif model.__name__ == "Work":
                    r.filter_by.return_value.first.return_value = MagicMock(title="末日科幻")
                    return r
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect

        context = build_supervisor_runtime_context(session_id="sess-1", db=mock_db)

        assert "sess-1" not in context
        assert "T1" in context or "completed" in context
        assert "T2" in context or "pending" in context

    def test_context_includes_next_executable_task(self):
        from app.services.supervisor.runtime_harness import build_supervisor_runtime_context

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.work_id = "w1"
        mock_session.status = "running"
        mock_session.ready_to_execute = True
        mock_session.active_child = None

        task1 = _make_task(id="t1", task_id="T1", status="completed", depends_on="")
        task2 = _make_task(id="t2", task_id="T2", status="pending", depends_on="T1")

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "TaskItem":
                    r.filter_by.return_value.order_by.return_value.all.return_value = [task1, task2]
                    return r
                elif model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
                elif model.__name__ == "Work":
                    r.filter_by.return_value.first.return_value = MagicMock(title="test")
                    return r
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect

        context = build_supervisor_runtime_context(session_id="sess-1", db=mock_db)

        assert "T2" in context or "创建大纲" in context


# ── Phase 9: Tool Policy Harness ──


class TestToolPolicyHarness:
    """验证 validate_tool_call_policy"""

    def test_warns_direct_dispatch_with_pending_todolist(self):
        from app.services.supervisor.runtime_harness import validate_tool_call_policy

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.ready_to_execute = True

        task1 = _make_task(id="t1", task_id="T1", status="pending")

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "TaskItem":
                    r.filter_by.return_value.all.return_value = [task1]
                    r.filter_by.return_value.count.return_value = 1
                    return r
                elif model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect

        decision = validate_tool_call_policy(
            tool_name="dispatch_chapter",
            tool_args={"instruction": "写第一章"},
            session_id="sess-1",
            db=mock_db,
        )

        assert decision["allowed"] is True  # First phase: only warn
        assert "warning" in decision or "execute_todo_task" in decision.get("reason", "")

    def test_allows_execute_todo_task(self):
        from app.services.supervisor.runtime_harness import validate_tool_call_policy

        mock_db = MagicMock()
        decision = validate_tool_call_policy(
            tool_name="execute_todo_task",
            tool_args={"task_item_id": "t1"},
            session_id="sess-1",
            db=mock_db,
        )

        assert decision["allowed"] is True
        assert decision.get("warning", "") == ""

    def test_allows_query_tools(self):
        from app.services.supervisor.runtime_harness import validate_tool_call_policy

        mock_db = MagicMock()
        decision = validate_tool_call_policy(
            tool_name="query_chapters",
            tool_args={},
            session_id="sess-1",
            db=mock_db,
        )

        assert decision["allowed"] is True
        assert decision.get("warning", "") == ""


# ── Phase 10: Child Agent Harness ──


class TestChildAgentHarness:
    """验证 set_active_child / clear_active_child"""

    def test_set_active_child_includes_task_item_id(self):
        from app.services.supervisor.runtime_harness import set_active_child

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.status = "running"
        mock_session.active_child = None

        set_active_child(
            session=mock_session,
            child_type="edit_outline",
            payload={"work_id": "w1"},
            task_item_id="task-uuid-1",
            db=mock_db,
        )

        assert mock_session.status == "waiting"
        assert mock_session.active_child["type"] == "edit_outline"
        assert mock_session.active_child["task_item_id"] == "task-uuid-1"
        mock_db.commit.assert_called()

    def test_clear_active_child_resets_session(self):
        from app.services.supervisor.runtime_harness import clear_active_child

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.status = "waiting"
        mock_session.active_child = {"type": "edit_chapter"}

        clear_active_child(session=mock_session, db=mock_db)

        assert mock_session.active_child is None
        mock_db.commit.assert_called()


# ── Phase 11: Recovery Harness ──


class TestRecoveryHarness:
    """验证 recover_session_on_resume"""

    def test_recovers_stale_running_session(self):
        from app.services.supervisor.runtime_harness import recover_session_on_resume

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.status = "running"
        mock_session.active_child = None

        stale_task = _make_task(
            status="in_progress",
            started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "TaskItem":
                    r.filter_by.return_value.all.return_value = [stale_task]
                    return r
                elif model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect

        emitted = []
        result = recover_session_on_resume(
            session_id="sess-1",
            db=mock_db,
            emit=lambda e, d: emitted.append((e, d)),
        )

        assert stale_task.status == "failed"
        assert result["recovered"] is True

    def test_keeps_waiting_session_intact(self):
        from app.services.supervisor.runtime_harness import recover_session_on_resume

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.status = "waiting"
        mock_session.active_child = {"type": "edit_chapter"}

        def query_side_effect(model):
            r = MagicMock()
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect

        result = recover_session_on_resume(
            session_id="sess-1",
            db=mock_db,
            emit=lambda e, d: None,
        )

        assert result["recovered"] is False
        assert mock_session.status == "waiting"


# ── Phase 12: Observability Harness ──


class TestObservabilityHarness:
    """验证 log_run_event"""

    @patch("app.routers.supervisor_router.message_service")
    def test_log_run_event_persists_to_messages(self, mock_msg_service):
        from app.services.supervisor.runtime_harness import log_run_event

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.work_id = "w1"

        def query_side_effect(model):
            r = MagicMock()
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect
        mock_msg_service.get_next_sort_order.return_value = 10

        log_run_event(
            session_id="sess-1",
            run_id="run-abc123",
            event_type="tool_policy_warning",
            db=mock_db,
            payload={"tool": "dispatch_chapter", "reason": "pending todolist exists"},
        )

        mock_msg_service.create_message.assert_called_once()
        call_kwargs = mock_msg_service.create_message.call_args[1]
        assert call_kwargs["meta"]["type"] == "supervisor_runtime_event"
        assert call_kwargs["meta"]["run_id"] == "run-abc123"
        assert call_kwargs["meta"]["event"] == "tool_policy_warning"

    @patch("app.routers.supervisor_router.message_service")
    def test_event_includes_run_id_and_event_type(self, mock_msg_service):
        from app.services.supervisor.runtime_harness import log_run_event

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.work_id = None

        def query_side_effect(model):
            r = MagicMock()
            r.filter_by.return_value.first.return_value = mock_session
            return r

        mock_db.query.side_effect = query_side_effect
        mock_msg_service.get_next_sort_order.return_value = 1

        log_run_event(
            session_id="sess-1",
            run_id="run-xyz",
            event_type="run_completed",
            db=mock_db,
            payload={"tasks_completed": 3},
        )

        call_kwargs = mock_msg_service.create_message.call_args[1]
        meta = call_kwargs["meta"]
        assert meta["run_id"] == "run-xyz"
        assert meta["event"] == "run_completed"
        assert meta["payload"]["tasks_completed"] == 3
