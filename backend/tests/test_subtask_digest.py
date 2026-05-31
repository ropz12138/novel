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

    def order_by(self, *args, **kwargs):
        self.rows.sort(key=lambda row: (getattr(row, "sort_order", 0), getattr(row, "created_at", None)))
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.rows = rows

    def query(self, model):
        return _Query(self.rows)


def test_build_subtask_digest_with_children():
    from app.services.supervisor.todo_harness import build_subtask_digest

    parent = TaskItem(id="p1", session_id="s1", task_id="T1", task_description="编辑章节")
    children = [
        TaskItem(
            id="c1",
            session_id="s1",
            parent_id="p1",
            task_id="T1.1",
            task_description="删除开篇呓语",
            status="completed",
            result_summary="已删除开篇呓语",
            sort_order=1,
        ),
        TaskItem(
            id="c2",
            session_id="s1",
            parent_id="p1",
            task_id="T1.2",
            task_description="修正玉佩描写",
            status="failed",
            error_message="补丁无法匹配",
            sort_order=2,
        ),
    ]

    digest = build_subtask_digest(parent=parent, db=_Db([parent, *children]))

    assert "执行明细" in digest
    assert "✓ [T1.1] 已删除开篇呓语" in digest
    assert "✗ [T1.2] 补丁无法匹配" in digest


def test_execute_todo_task_return_includes_digest():
    from app.services.supervisor.todo_harness import _compose_task_summary

    summary = _compose_task_summary(
        result_message="章节任务已完成。",
        dispatch_result={"ok": True, "status": "completed", "payload": {"title": "第一章"}},
        subtask_digest="执行明细：\n  ✓ [T1.1] 已删除开篇呓语",
    )

    assert "章节任务已完成" in summary
    assert "结构化结果" in summary
    assert "执行明细" in summary
