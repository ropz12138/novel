"""Todolist 服务 — 纯持久化，无内部 LLM。"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from models.todo_item import TodoItem

MAX_TODO_TASKS = 8
MAX_TASK_TEXT_LEN = 500
VALID_ACTIONS = frozenset({"complete", "add", "edit", "remove"})
TASK_ID_PATTERN = re.compile(r"^T(\d+)$", re.IGNORECASE)


@dataclass
class TodoServiceResult:
    message: str
    events: list[tuple[str, dict]] = field(default_factory=list)
    ok: bool = True


def serialize_todo_item(item: TodoItem) -> dict:
    return {
        "db_id": item.id,
        "task_id": item.task_id,
        "task": item.task,
        "status": item.status,
    }


def list_todo_items(db: Session, session_id: str) -> list[TodoItem]:
    return (
        db.query(TodoItem)
        .filter_by(session_id=session_id)
        .order_by(TodoItem.sort_order.asc(), TodoItem.created_at.asc())
        .all()
    )


def _normalize_tasks(tasks: list[str]) -> tuple[list[str] | None, str]:
    if not tasks:
        return None, "创建任务清单失败：tasks 不能为空。"
    normalized: list[str] = []
    for raw in tasks:
        text = str(raw or "").strip()
        if not text:
            return None, "创建任务清单失败：每条 task 必须是非空字符串。"
        if len(text) > MAX_TASK_TEXT_LEN:
            return None, f"创建任务清单失败：单条 task 不能超过 {MAX_TASK_TEXT_LEN} 字。"
        normalized.append(text)
    if len(normalized) > MAX_TODO_TASKS:
        return None, f"创建任务清单失败：最多 {MAX_TODO_TASKS} 条任务。"
    return normalized, ""


def _fail(msg: str) -> TodoServiceResult:
    return TodoServiceResult(message=msg, ok=False)


def _todolist_generated_event(items: list[TodoItem]) -> tuple[str, dict]:
    return (
        "todolist_generated",
        {
            "todolist": [serialize_todo_item(t) for t in items],
            "ready_to_execute": True,
        },
    )


def _next_task_id(existing: list[TodoItem]) -> str:
    max_num = 0
    for item in existing:
        match = TASK_ID_PATTERN.match(item.task_id or "")
        if match:
            max_num = max(max_num, int(match.group(1)))
    return f"T{max_num + 1}"


def _find_by_task_id(items: list[TodoItem], task_id: str) -> TodoItem | None:
    key = (task_id or "").strip().upper()
    for item in items:
        if (item.task_id or "").upper() == key:
            return item
    return None


def write_todolist(
    session_id: str,
    tasks: list[str],
    db: Session,
) -> TodoServiceResult:
    if not session_id:
        return _fail("创建任务清单失败：当前会话未绑定 session_id。")

    normalized, err = _normalize_tasks(tasks)
    if err:
        return _fail(err)

    db.query(TodoItem).filter_by(session_id=session_id).delete()

    created: list[TodoItem] = []
    for idx, text in enumerate(normalized, start=1):
        item = TodoItem(
            id=str(uuid.uuid4()),
            session_id=session_id,
            task_id=f"T{idx}",
            task=text,
            status="pending",
            sort_order=idx,
        )
        db.add(item)
        created.append(item)

    db.commit()
    for item in created:
        db.refresh(item)

    lines = [f"- {t.task_id}: {t.task}" for t in created]
    return TodoServiceResult(
        message="任务清单已创建，共 {} 条：\n{}".format(len(created), "\n".join(lines)),
        events=[_todolist_generated_event(created)],
    )


def update_todolist(
    session_id: str,
    action: str,
    db: Session,
    *,
    task_id: str | None = None,
    task: str | None = None,
    tasks: list[str] | None = None,
) -> TodoServiceResult:
    if not session_id:
        return _fail("更新任务清单失败：当前会话未绑定 session_id。")

    action_key = (action or "").strip().lower()
    if action_key not in VALID_ACTIONS:
        return _fail(
            f"更新任务清单失败：无效 action「{action}」，合法值为 complete / add / edit / remove。"
        )

    items = list_todo_items(db, session_id)
    if not items and action_key != "add":
        return _fail("更新任务清单失败：当前会话还没有任务清单，请先调用 write_todolist。")

    if action_key == "complete":
        if not task_id:
            return _fail("更新任务清单失败：complete 需要 task_id。")
        target = _find_by_task_id(items, task_id)
        if not target:
            return _fail(f"更新任务清单失败：任务 {task_id} 不存在。")
        if target.status == "completed":
            return _fail(f"更新任务清单失败：任务 {target.task_id} 已完成，不能重复打勾。")
        old_status = target.status
        target.status = "completed"
        db.commit()
        return TodoServiceResult(
            message=f"任务 {target.task_id} 已标记完成：{target.task}",
            events=[
                (
                    "task_status_updated",
                    {
                        "task_item_id": target.id,
                        "task_id": target.task_id,
                        "old_status": old_status,
                        "new_status": "completed",
                    },
                )
            ],
        )

    if action_key == "add":
        new_texts, err = _normalize_tasks(tasks or [])
        if err:
            return _fail(err.replace("创建任务清单失败", "追加任务失败"))
        if len(items) + len(new_texts) > MAX_TODO_TASKS:
            return _fail(f"追加任务失败：任务总数不能超过 {MAX_TODO_TASKS} 条。")
        appended: list[TodoItem] = []
        for text in new_texts:
            new_id = _next_task_id(items + appended)
            item = TodoItem(
                id=str(uuid.uuid4()),
                session_id=session_id,
                task_id=new_id,
                task=text,
                status="pending",
                sort_order=len(items) + len(appended) + 1,
            )
            db.add(item)
            appended.append(item)
        db.commit()
        for item in appended:
            db.refresh(item)
        events = [
            (
                "todolist_task_added",
                {
                    "db_id": item.id,
                    "task_id": item.task_id,
                    "task_description": item.task,
                    "sort_order": item.sort_order,
                },
            )
            for item in appended
        ]
        ids = ", ".join(i.task_id for i in appended)
        return TodoServiceResult(
            message=f"已追加 {len(appended)} 条任务：{ids}",
            events=events,
        )

    if action_key == "edit":
        if not task_id:
            return _fail("更新任务清单失败：edit 需要 task_id。")
        new_text = str(task or "").strip()
        if not new_text:
            return _fail("更新任务清单失败：edit 需要非空 task 文案。")
        if len(new_text) > MAX_TASK_TEXT_LEN:
            return _fail(f"更新任务清单失败：单条 task 不能超过 {MAX_TASK_TEXT_LEN} 字。")
        target = _find_by_task_id(items, task_id)
        if not target:
            return _fail(f"更新任务清单失败：任务 {task_id} 不存在。")
        if target.status == "completed":
            return _fail(f"更新任务清单失败：任务 {target.task_id} 已完成，不能修改。")
        target.task = new_text
        db.commit()
        return TodoServiceResult(
            message=f"任务 {target.task_id} 已更新为：{target.task}",
            events=[
                (
                    "todolist_task_edited",
                    {
                        "db_id": target.id,
                        "task_id": target.task_id,
                        "task_description": target.task,
                    },
                )
            ],
        )

    if action_key == "remove":
        if not task_id:
            return _fail("更新任务清单失败：remove 需要 task_id。")
        target = _find_by_task_id(items, task_id)
        if not target:
            return _fail(f"更新任务清单失败：任务 {task_id} 不存在。")
        if target.status == "completed":
            return _fail(f"更新任务清单失败：任务 {target.task_id} 已完成，不能删除。")
        removed_id = target.task_id
        removed_db_id = target.id
        db.delete(target)
        db.commit()
        return TodoServiceResult(
            message=f"任务 {removed_id} 已删除。",
            events=[
                ("todolist_task_deleted", {"db_id": removed_db_id, "task_id": removed_id})
            ],
        )

    return _fail("更新任务清单失败：未知错误。")
