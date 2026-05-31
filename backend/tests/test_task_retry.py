import pytest

from app.models.task_item_model import TaskItem


class _Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter_by(self, **kwargs):
        self.rows = [
            row
            for row in self.rows
            if all(getattr(row, key, None) == value for key, value in kwargs.items())
        ]
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, rows):
        self.rows = list(rows)
        self.commits = 0

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "TaskItem":
            return _Query([row for row in self.rows if isinstance(row, TaskItem)])
        return _Query([row for row in self.rows if not isinstance(row, TaskItem)])

    def delete(self, row):
        self.rows.remove(row)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _task(**overrides):
    defaults = dict(
        id="task-1",
        session_id="sess-1",
        task_id="T1",
        task_description="评估章节",
        owner="evaluation_agent",
        status="failed",
        dispatch_tool="dispatch_evaluation",
        instruction="评估第1章",
    )
    defaults.update(overrides)
    return TaskItem(**defaults)


def test_retry_count_column_migration_declared():
    from app.models.task_item_model import TaskItem

    assert hasattr(TaskItem, "retry_count")
    assert TaskItem(id="x", session_id="s", task_id="T1").retry_count == 0


@pytest.mark.asyncio
async def test_failed_task_can_retry_within_limit(monkeypatch):
    from app.services.supervisor import todo_harness

    task = _task(retry_count=0, error_message="上次失败")
    db = _Db([task])
    emitted = []

    async def fake_dispatch(**kwargs):
        return '{"ok": true, "status": "completed", "message": "评估完成", "payload": {}}'

    monkeypatch.setattr(todo_harness, "_dispatch_by_tool", fake_dispatch)

    result = await todo_harness.execute_todo_task(
        task_item_id=task.id,
        db=db,
        emit=lambda event, data: emitted.append((event, data)),
        config={"configurable": {"supervisor_session_id": "sess-1"}},
    )

    assert task.retry_count == 1
    assert task.status == "completed"
    assert task.error_message == ""
    assert "执行完成" in result
    assert any(event == "task_retry" for event, _ in emitted)


@pytest.mark.asyncio
async def test_failed_task_blocked_after_limit():
    from app.services.supervisor.todo_harness import MAX_TASK_RETRIES, execute_todo_task

    task = _task(retry_count=MAX_TASK_RETRIES)
    result = await execute_todo_task(
        task_item_id=task.id,
        db=_Db([task]),
        emit=lambda event, data: None,
        config={"configurable": {}},
    )

    assert "重试上限" in result
    assert task.status == "failed"


@pytest.mark.asyncio
async def test_completed_task_still_not_retriable():
    from app.services.supervisor.todo_harness import execute_todo_task

    task = _task(status="completed")
    result = await execute_todo_task(
        task_item_id=task.id,
        db=_Db([task]),
        emit=lambda event, data: None,
        config={"configurable": {}},
    )

    assert "不可执行" in result
    assert task.status == "completed"
