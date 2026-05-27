"""Phase 6 测试：Reconciliation 兜底

验证：
1. reconcile_stale_tasks 检测超时的 in_progress 任务并标记为 failed
2. reconcile_stale_tasks 不影响正常 in_progress 任务（有 waiting session）
3. reconcile_stale_tasks 不影响 pending/completed/skipped/failed 任务
4. reconcile_session_tasks 检测没有 waiting session 但有 in_progress 任务的异常
5. reconcile 为 supervisor._run_graph 提供入口点
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

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


class TestReconcileStaleTasks:
    """验证 stale task 检测和修复"""

    def test_marks_stale_in_progress_as_failed(self):
        """超时的 in_progress 任务应标记为 failed"""
        from app.services.supervisor.todo_harness import reconcile_stale_tasks

        mock_db = MagicMock()
        old_time = datetime.now(timezone.utc) - timedelta(hours=3)
        stale_task = _make_task(
            status="in_progress",
            started_at=old_time,
        )

        # session 不在 waiting 状态
        mock_session = MagicMock()
        mock_session.status = "completed"
        mock_session.active_child = None

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "TaskItem":
                    r.filter_by.return_value.all.return_value = [stale_task]
                    return r
                elif model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.all.return_value = [stale_task]
            return r

        mock_db.query.side_effect = query_side_effect

        emitted = []
        result = reconcile_stale_tasks(
            session_id="sess-1",
            db=mock_db,
            stale_threshold_minutes=60,
            emit=lambda e, d: emitted.append((e, d)),
        )

        assert stale_task.status == "failed"
        assert "stale" in stale_task.error_message.lower() or "超时" in stale_task.error_message
        assert result["reconciled"] == 1

    def test_does_not_mark_recent_in_progress(self):
        """最近开始的 in_progress 任务不应被标记"""
        from app.services.supervisor.todo_harness import reconcile_stale_tasks

        mock_db = MagicMock()
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_task = _make_task(
            status="in_progress",
            started_at=recent_time,
        )

        mock_session = MagicMock()
        mock_session.status = "running"
        mock_session.active_child = None

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "TaskItem":
                    r.filter_by.return_value.all.return_value = [recent_task]
                    return r
                elif model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.all.return_value = [recent_task]
            return r

        mock_db.query.side_effect = query_side_effect

        result = reconcile_stale_tasks(
            session_id="sess-1",
            db=mock_db,
            stale_threshold_minutes=60,
            emit=lambda e, d: None,
        )

        assert recent_task.status == "in_progress"
        assert result["reconciled"] == 0

    def test_does_not_mark_waiting_session_tasks(self):
        """session 在 waiting 状态时，in_progress 任务不应被标记"""
        from app.services.supervisor.todo_harness import reconcile_stale_tasks

        mock_db = MagicMock()
        old_time = datetime.now(timezone.utc) - timedelta(hours=3)
        waiting_task = _make_task(
            status="in_progress",
            started_at=old_time,
        )

        mock_session = MagicMock()
        mock_session.status = "waiting"
        mock_session.active_child = {"type": "edit_outline", "work_id": "w1"}

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "TaskItem":
                    r.filter_by.return_value.all.return_value = [waiting_task]
                    return r
                elif model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.all.return_value = [waiting_task]
            return r

        mock_db.query.side_effect = query_side_effect

        result = reconcile_stale_tasks(
            session_id="sess-1",
            db=mock_db,
            stale_threshold_minutes=60,
            emit=lambda e, d: None,
        )

        assert waiting_task.status == "in_progress"
        assert result["reconciled"] == 0

    def test_does_not_affect_non_in_progress_tasks(self):
        """pending/completed/skipped/failed 任务不受影响"""
        from app.services.supervisor.todo_harness import reconcile_stale_tasks

        mock_db = MagicMock()
        pending = _make_task(id="t1", task_id="T1", status="pending")
        completed = _make_task(id="t2", task_id="T2", status="completed")
        failed = _make_task(id="t3", task_id="T3", status="failed")

        mock_session = MagicMock()
        mock_session.status = "completed"

        def query_side_effect(model):
            r = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "TaskItem":
                    r.filter_by.return_value.all.return_value = [pending, completed, failed]
                    return r
                elif model.__name__ == "SupervisorSession":
                    r.filter_by.return_value.first.return_value = mock_session
                    return r
            r.filter_by.return_value.all.return_value = [pending, completed, failed]
            return r

        mock_db.query.side_effect = query_side_effect

        result = reconcile_stale_tasks(
            session_id="sess-1",
            db=mock_db,
            stale_threshold_minutes=60,
            emit=lambda e, d: None,
        )

        assert pending.status == "pending"
        assert completed.status == "completed"
        assert failed.status == "failed"
        assert result["reconciled"] == 0
