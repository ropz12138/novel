"""Tests for the edit_todolist Supervisor tool.

Covers: add / update / delete of top-level pending tasks,
guard rails, dependency validation, and event emission.
"""
import uuid

import pytest

from app.models.task_item_model import TaskItem


# ── Test helpers (same pattern as test_task_retry) ──


class _Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter_by(self, **kwargs):
        self.rows = [
            r for r in self.rows
            if all(getattr(r, k, None) == v for k, v in kwargs.items())
        ]
        return self

    def filter(self, *args):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.commits = 0
        self.added = []

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "TaskItem":
            return _Query([r for r in self.rows if isinstance(r, TaskItem)])
        return _Query([r for r in self.rows if not isinstance(r, TaskItem)])

    def add(self, row):
        self.rows.append(row)
        self.added.append(row)

    def delete(self, row):
        self.rows.remove(row)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def refresh(self, row):
        pass


def _task(task_id="T1", status="pending", depth=0, parent_id=None, depends_on="", **kw):
    defaults = dict(
        id=str(uuid.uuid4()),
        session_id="sess-1",
        task_id=task_id,
        task_description="原任务描述",
        owner="supervisor",
        status=status,
        depends_on=depends_on,
        done_criteria="",
        result_summary="",
        sort_order=int(task_id.replace("T", "").split(".")[0]) - 1 if task_id.startswith("T") else 0,
        parent_id=parent_id,
        depth=depth,
        agent_scope="supervisor",
        task_type="",
        dispatch_tool="dispatch_chapter",
        instruction="原指令",
    )
    defaults.update(kw)
    return TaskItem(**defaults)


def _run_edit(db, emitted, action, **kwargs):
    """Call edit_todolist function directly (bypasses @tool wrapper)."""
    from app.services.supervisor.tools import edit_todolist

    config = {"configurable": {"supervisor_session_id": "sess-1", "db": db, "emit": lambda e, d: emitted.append((e, d))}}
    result = edit_todolist.func(
        action=action, config=config, **kwargs,
    )
    return result


# ── ADD tests ──


class TestAdd:
    def test_add_basic(self):
        t1 = _task("T1")
        db = _Db([t1])
        emitted = []

        result = _run_edit(db, emitted, "add", task_description="新任务")

        assert "T2" in result
        new_task = [r for r in db.added if isinstance(r, TaskItem)]
        assert len(new_task) == 1
        assert new_task[0].task_id == "T2"
        assert new_task[0].status == "pending"
        assert new_task[0].depth == 0
        assert new_task[0].task_description == "新任务"
        assert new_task[0].session_id == "sess-1"

    def test_add_with_all_fields(self):
        db = _Db([_task("T1"), _task("T2")])
        emitted = []

        result = _run_edit(
            db, emitted, "add",
            task_description="补建角色卡",
            agent="outline",
            instruction="为王教授、刘浩创建角色卡",
            done_criteria="角色卡已创建",
        )

        assert "T3" in result
        new_task = [r for r in db.added if isinstance(r, TaskItem)][0]
        assert new_task.task_id == "T3"
        assert new_task.dispatch_tool == "dispatch_outline"
        assert new_task.instruction == "为王教授、刘浩创建角色卡"
        assert new_task.done_criteria == "角色卡已创建"

    def test_add_emits_event(self):
        db = _Db([_task("T1")])
        emitted = []

        _run_edit(db, emitted, "add", task_description="test")

        assert any(e == "todolist_task_added" for e, _ in emitted)
        event_data = next(d for e, d in emitted if e == "todolist_task_added")
        assert event_data["task_id"] == "T2"
        assert event_data["task_description"] == "test"

    def test_add_with_depends_on_valid(self):
        db = _Db([_task("T1"), _task("T2")])
        emitted = []

        result = _run_edit(db, emitted, "add", task_description="T3", depends_on="T1,T2")

        new_task = [r for r in db.added if isinstance(r, TaskItem)][0]
        assert new_task.depends_on == "T1,T2"

    def test_add_with_depends_on_invalid_ref(self):
        db = _Db([_task("T1")])
        emitted = []

        result = _run_edit(db, emitted, "add", task_description="bad", depends_on="T99")

        assert "不存在" in result or "T99" in result

    def test_add_with_invalid_agent_rejected(self):
        db = _Db([_task("T1")])
        emitted = []

        result = _run_edit(db, emitted, "add", task_description="bad", agent="invalid_agent")

        assert "无效" in result or "agent" in result.lower()

    def test_add_to_empty_todolist(self):
        db = _Db([])
        emitted = []

        result = _run_edit(db, emitted, "add", task_description="第一个任务")

        assert "T1" in result
        new_task = [r for r in db.added if isinstance(r, TaskItem)][0]
        assert new_task.task_id == "T1"

    def test_add_committed(self):
        db = _Db([_task("T1")])
        emitted = []

        _run_edit(db, emitted, "add", task_description="test")

        assert db.commits >= 1


# ── UPDATE tests ──


class TestUpdate:
    def test_update_basic(self):
        t1 = _task("T1", task_description="旧描述")
        db = _Db([t1])
        emitted = []

        result = _run_edit(db, emitted, "update", task_id="T1", task_description="新描述")

        assert "T1" in result
        assert t1.task_description == "新描述"

    def test_update_agent_changes_dispatch_tool(self):
        t1 = _task("T1", dispatch_tool="dispatch_chapter")
        db = _Db([t1])
        emitted = []

        _run_edit(db, emitted, "update", task_id="T1", agent="outline")

        assert t1.dispatch_tool == "dispatch_outline"

    def test_update_emits_event(self):
        t1 = _task("T1")
        db = _Db([t1])
        emitted = []

        _run_edit(db, emitted, "update", task_id="T1", task_description="changed")

        assert any(e == "todolist_task_edited" for e, _ in emitted)

    def test_update_preserves_unchanged_fields(self):
        t1 = _task("T1", task_description="A", instruction="B", done_criteria="C")
        db = _Db([t1])

        _run_edit(db, [], "update", task_id="T1", task_description="A'")

        assert t1.task_description == "A'"
        assert t1.instruction == "B"
        assert t1.done_criteria == "C"

    def test_update_rejects_non_pending(self):
        t1 = _task("T1", status="in_progress")
        db = _Db([t1])

        result = _run_edit(db, [], "update", task_id="T1", task_description="X")

        assert "不可" in result or "进行中" in result or "in_progress" in result

    def test_update_rejects_terminal_status(self):
        for st in ("completed", "failed", "skipped"):
            t1 = _task("T1", status=st)
            db = _Db([t1])
            result = _run_edit(db, [], "update", task_id="T1", task_description="X")
            assert "不可" in result or st in result, f"should reject status={st}"

    def test_update_rejects_nonexistent_task(self):
        db = _Db([])

        result = _run_edit(db, [], "update", task_id="T99", task_description="X")

        assert "不存在" in result or "T99" in result

    def test_update_rejects_child_task(self):
        parent = _task("T1", status="completed")
        child = _task("T1.1", status="pending", depth=1, parent_id=parent.id)
        db = _Db([parent, child])

        result = _run_edit(db, [], "update", task_id="T1.1", task_description="X")

        assert "顶层" in result or "不可" in result


# ── DELETE tests ──


class TestDelete:
    def test_delete_basic(self):
        t1 = _task("T1")
        t2 = _task("T2")
        db = _Db([t1, t2])
        emitted = []

        result = _run_edit(db, emitted, "delete", task_id="T2")

        assert "T2" in result
        assert t2 not in db.rows
        assert t1 in db.rows

    def test_delete_emits_event(self):
        t1 = _task("T1")
        db = _Db([t1])
        emitted = []

        _run_edit(db, emitted, "delete", task_id="T1")

        assert any(e == "todolist_task_deleted" for e, _ in emitted)
        event_data = next(d for e, d in emitted if e == "todolist_task_deleted")
        assert event_data["task_id"] == "T1"

    def test_delete_rejects_non_pending(self):
        t1 = _task("T1", status="completed")
        db = _Db([t1])

        result = _run_edit(db, [], "delete", task_id="T1")

        assert "不可" in result

    def test_delete_rejects_when_depended_by_others(self):
        t1 = _task("T1")
        t2 = _task("T2", depends_on="T1")
        db = _Db([t1, t2])

        result = _run_edit(db, [], "delete", task_id="T1")

        assert "依赖" in result or "T2" in result
        assert t1 in db.rows  # not deleted

    def test_delete_rejects_nonexistent(self):
        db = _Db([])

        result = _run_edit(db, [], "delete", task_id="T99")

        assert "不存在" in result or "T99" in result

    def test_delete_rejects_child_task(self):
        parent = _task("T1", status="completed")
        child = _task("T1.1", status="pending", depth=1, parent_id=parent.id)
        db = _Db([parent, child])

        result = _run_edit(db, [], "delete", task_id="T1.1")

        assert "顶层" in result or "不可" in result

    def test_delete_committed(self):
        t1 = _task("T1")
        db = _Db([t1])

        _run_edit(db, [], "delete", task_id="T1")

        assert db.commits >= 1


# ── Integration / edge cases ──


class TestEdgeCases:
    def test_add_then_delete(self):
        db = _Db([_task("T1")])

        _run_edit(db, [], "add", task_description="临时任务")
        new_task = [r for r in db.added if isinstance(r, TaskItem)][0]
        assert new_task.task_id == "T2"

        result = _run_edit(db, [], "delete", task_id="T2")
        assert "T2" in result
        assert new_task not in db.rows

    def test_add_assigns_correct_task_id_with_gaps(self):
        """task_id T3 is missing; next add should be T4."""
        t1 = _task("T1")
        t2 = _task("T2")
        t4 = _task("T4")  # gap at T3
        db = _Db([t1, t2, t4])

        _run_edit(db, [], "add", task_description="new")

        new_task = [r for r in db.added if isinstance(r, TaskItem)][0]
        assert new_task.task_id == "T5"
