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

    def query(self, model):
        if getattr(model, "__name__", "") == "TaskItem":
            return _Query([row for row in self.rows if isinstance(row, TaskItem)])
        return _Query([])

    def commit(self):
        pass

    def rollback(self):
        pass


def _task(**overrides):
    defaults = dict(
        id="task-1",
        session_id="sess-1",
        task_id="T1",
        task_description="执行任务",
        owner="chapter_agent",
        status="pending",
        dispatch_tool="dispatch_chapter",
        instruction="写一章",
    )
    defaults.update(overrides)
    return TaskItem(**defaults)


@pytest.mark.asyncio
async def test_agent_override_routes_correctly(monkeypatch):
    from app.services.supervisor import todo_harness

    task = _task(dispatch_tool="dispatch_chapter")
    seen = {}

    async def fake_dispatch(**kwargs):
        seen["dispatch_tool"] = kwargs["dispatch_tool"]
        return '{"ok": true, "status": "completed", "message": "评估完成", "payload": {}}'

    monkeypatch.setattr(todo_harness, "_dispatch_by_tool", fake_dispatch)

    await todo_harness.execute_todo_task(
        task_item_id=task.id,
        db=_Db([task]),
        emit=lambda event, data: None,
        config={"configurable": {"supervisor_session_id": "sess-1"}},
        agent="evaluation",
    )

    assert seen["dispatch_tool"] == "dispatch_evaluation"
    assert task.dispatch_tool == "dispatch_evaluation"


@pytest.mark.asyncio
async def test_invalid_agent_rejected(monkeypatch):
    from app.services.supervisor import todo_harness

    task = _task()
    called = False

    async def fake_dispatch(**kwargs):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(todo_harness, "_dispatch_by_tool", fake_dispatch)

    result = await todo_harness.execute_todo_task(
        task_item_id=task.id,
        db=_Db([task]),
        emit=lambda event, data: None,
        config={"configurable": {}},
        agent="bad-agent",
    )

    assert "无效 agent" in result
    assert called is False
    assert task.status == "pending"


@pytest.mark.asyncio
async def test_no_agent_falls_back_to_inference(monkeypatch):
    from app.services.supervisor import todo_harness

    task = _task(dispatch_tool="", owner="evaluation_agent")
    seen = {}

    async def fake_dispatch(**kwargs):
        seen["dispatch_tool"] = kwargs["dispatch_tool"]
        return '{"ok": true, "status": "completed", "message": "评估完成", "payload": {}}'

    monkeypatch.setattr(todo_harness, "_dispatch_by_tool", fake_dispatch)

    await todo_harness.execute_todo_task(
        task_item_id=task.id,
        db=_Db([task]),
        emit=lambda event, data: None,
        config={"configurable": {"supervisor_session_id": "sess-1"}},
    )

    assert seen["dispatch_tool"] == "dispatch_evaluation"
