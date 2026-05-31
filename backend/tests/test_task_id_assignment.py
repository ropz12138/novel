from app.models.task_item_model import TaskItem


class _PlannerTask:
    def __init__(self, id="", depends_on=None):
        self.id = id
        self.depends_on = depends_on or []


class _Query:
    def __init__(self, db, rows):
        self.db = db
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

    def first(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, rows):
        self.rows = list(rows)

    def query(self, model):
        return _Query(self, self.rows)

    def add(self, row):
        self.rows.append(row)

    def commit(self):
        pass

    def rollback(self):
        pass


def test_child_ids_are_dotted():
    from app.services.supervisor.todo_harness import _allocate_child_task_id

    used = set()
    assert _allocate_child_task_id(raw_task_id="T1", parent_task_id="T7", index=1, used_ids=used) == "T7.1"
    assert _allocate_child_task_id(raw_task_id="custom", parent_task_id="T7", index=2, used_ids=used) == "T7.2"


def test_top_level_ids_are_sequential():
    from app.services.supervisor.tools import _remap_top_level_task_ids

    mapping, remapped = _remap_top_level_task_ids([
        _PlannerTask(id="outline"),
        _PlannerTask(id="write"),
        _PlannerTask(id="review"),
    ])

    assert mapping["outline"] == "T1"
    assert mapping["write"] == "T2"
    assert mapping["review"] == "T3"
    assert remapped == [[], [], []]


def test_top_level_depends_on_remapped():
    from app.services.supervisor.tools import _remap_top_level_task_ids

    mapping, remapped = _remap_top_level_task_ids([
        _PlannerTask(id="outline"),
        _PlannerTask(id="write", depends_on=["outline"]),
        _PlannerTask(id="review", depends_on=["write"]),
    ])

    assert mapping == {"outline": "T1", "T1": "T1", "write": "T2", "T2": "T2", "review": "T3", "T3": "T3"}
    assert remapped == [[], ["T1"], ["T2"]]


def test_child_depends_on_remapped():
    from app.services.supervisor.todo_harness import create_child_todolist

    parent = TaskItem(
        id="parent-1",
        session_id="sess-1",
        task_id="T2",
        task_description="编辑章节",
        owner="chapter_agent",
    )
    db = _Db([parent])

    create_child_todolist(
        items=[
            {"id": "draft", "task": "草拟修改"},
            {"id": "apply", "task": "应用修改", "depends_on": ["draft"]},
        ],
        db=db,
        emit=lambda event, data: None,
        config={"configurable": {"current_task_item_id": "parent-1", "supervisor_session_id": "sess-1"}},
    )

    children = [row for row in db.rows if row.parent_id == "parent-1"]
    assert [child.task_id for child in children] == ["T2.1", "T2.2"]
    assert children[1].depends_on == "T2.1"


def test_no_id_collision_in_session():
    parent = TaskItem(id="p", session_id="s", task_id="T1", task_description="父任务")
    child = TaskItem(id="c", session_id="s", parent_id="p", task_id="T1.1", task_description="子任务")

    assert parent.task_id != child.task_id
