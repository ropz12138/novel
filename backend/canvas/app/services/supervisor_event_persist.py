"""Supervisor SSE 事件持久化 — 使 Todolist 刷新后可恢复。"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.session import SupervisorMessage, SupervisorSession
from app.services.todo_service import list_todo_items, serialize_todo_item

PERSISTABLE_TODO_EVENTS = frozenset({
    "todolist_generated",
    "task_status_updated",
    "todolist_task_added",
    "todolist_task_edited",
    "todolist_task_deleted",
})

PERSISTABLE_DIFF_EVENTS = frozenset({
    "chapter_edit_diff",
})


def _next_sort_order(db: Session, session_id: str) -> int:
    row = (
        db.query(SupervisorMessage.sort_order)
        .filter_by(session_id=session_id)
        .order_by(SupervisorMessage.sort_order.desc())
        .first()
    )
    return (row[0] + 1) if row else 0


def _find_latest_todolist_message(db: Session, session_id: str) -> SupervisorMessage | None:
    msgs = (
        db.query(SupervisorMessage)
        .filter_by(session_id=session_id)
        .order_by(SupervisorMessage.sort_order.desc())
        .all()
    )
    for msg in msgs:
        meta = msg.meta or {}
        if msg.role == "assistant" and meta.get("type") == "requirements_todolist" and meta.get("todoCard"):
            return msg
    return None


def _build_todo_card_from_db(db: Session, session_id: str) -> dict | None:
    items = list_todo_items(db, session_id)
    if not items:
        return None
    return {
        "intent_summary": "",
        "todolist": [serialize_todo_item(t) for t in items],
        "ready_to_execute": True,
    }


def _persist_diff_event(db: Session, session_id: str, event: str, data: dict) -> bool:
    """将 chapter_edit_diff 事件写入 supervisor_messages。"""
    sess = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not sess:
        return False

    if event == "chapter_edit_diff":
        diff = data.get("diff") or {}
        db.add(
            SupervisorMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="",
                work_id=sess.work_id,
                sort_order=_next_sort_order(db, session_id),
                meta={
                    "type": "chapter_content_diff_card",
                    "chapterContentDiffCard": {
                        "chapter_node_id": data.get("chapter_node_id", ""),
                        "title": data.get("title", ""),
                        "hunks": diff.get("hunks", []),
                        "summary": diff.get("summary", {}),
                        "word_count": data.get("word_count", 0),
                        "word_count_delta": data.get("word_count_delta", 0),
                    },
                },
            )
        )
        db.commit()
        return True

    return False


def persist_supervisor_event(db: Session, session_id: str, event: str, data: dict) -> bool:
    """将 Todolist/Diff 相关 SSE 事件写入 supervisor_messages。"""
    if event not in PERSISTABLE_TODO_EVENTS and event not in PERSISTABLE_DIFF_EVENTS:
        return False

    if event in PERSISTABLE_DIFF_EVENTS:
        return _persist_diff_event(db, session_id, event, data)

    sess = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not sess:
        return False

    if event == "todolist_generated":
        db.add(
            SupervisorMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="",
                work_id=sess.work_id,
                sort_order=_next_sort_order(db, session_id),
                meta={
                    "type": "requirements_todolist",
                    "event": event,
                    "todoCard": {
                        "intent_summary": data.get("intent_summary", ""),
                        "todolist": data.get("todolist", []),
                        "ready_to_execute": bool(data.get("ready_to_execute", True)),
                    },
                },
            )
        )
        db.commit()
        return True

    existing = _find_latest_todolist_message(db, session_id)
    if not existing:
        todo_card = _build_todo_card_from_db(db, session_id)
        if not todo_card:
            return False
        db.add(
            SupervisorMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="",
                work_id=sess.work_id,
                sort_order=_next_sort_order(db, session_id),
                meta={"type": "requirements_todolist", "event": event, "todoCard": todo_card},
            )
        )
        db.commit()
        existing = _find_latest_todolist_message(db, session_id)
        if not existing:
            return False

    meta = dict(existing.meta or {})
    todo_card = dict(meta.get("todoCard") or {})
    todolist = list(todo_card.get("todolist") or [])

    if event == "task_status_updated":
        target_id = data.get("task_item_id")
        for t in todolist:
            if t.get("db_id") == target_id:
                t["status"] = data.get("new_status", t.get("status"))
                break

    elif event == "todolist_task_added":
        todolist.append({
            "db_id": data.get("db_id"),
            "task_id": data.get("task_id"),
            "task": data.get("task_description"),
            "status": "pending",
            "sort_order": data.get("sort_order", len(todolist)),
        })

    elif event == "todolist_task_edited":
        target_id = data.get("db_id")
        for t in todolist:
            if t.get("db_id") == target_id:
                if data.get("task_description") is not None:
                    t["task"] = data.get("task_description")
                break

    elif event == "todolist_task_deleted":
        target_id = data.get("db_id")
        todolist = [t for t in todolist if t.get("db_id") != target_id]

    todo_card["todolist"] = todolist
    meta["todoCard"] = todo_card
    existing.meta = meta
    flag_modified(existing, "meta")
    db.commit()
    return True


def enrich_messages_with_todolist(
    db: Session,
    session_id: str,
    messages: list[dict],
) -> list[dict]:
    """从 todo_items 表同步最新清单，保证刷新后可展示。"""
    todo_card = _build_todo_card_from_db(db, session_id)
    if not todo_card:
        return messages

    result = [dict(m) for m in messages]
    last_idx = None
    for idx, msg in enumerate(result):
        meta = msg.get("meta") or {}
        if msg.get("role") == "assistant" and meta.get("type") == "requirements_todolist":
            last_idx = idx

    if last_idx is not None:
        msg = dict(result[last_idx])
        meta = dict(msg.get("meta") or {})
        meta["todoCard"] = todo_card
        msg["meta"] = meta
        result[last_idx] = msg
        return result

    result.append({
        "id": f"todo-snapshot-{session_id}",
        "session_id": session_id,
        "role": "assistant",
        "content": "",
        "meta": {"type": "requirements_todolist", "todoCard": todo_card},
    })
    return result


def persist_supervisor_event_safe(session_id: str, event: str, data: dict) -> None:
    """供 router emit 调用；独立 DB 会话，避免与 agent 事务冲突。"""
    if event not in PERSISTABLE_TODO_EVENTS and event not in PERSISTABLE_DIFF_EVENTS:
        return
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        persist_supervisor_event(db, session_id, event, data)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
