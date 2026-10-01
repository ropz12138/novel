"""聊天历史分页。Agent 仍通过 session_store.get_messages 读取完整记录。"""
from __future__ import annotations

from models.session import SupervisorMessage

HISTORY_PAGE_VISIBLE_LIMIT = 40
VISIBLE_ROLES = frozenset({"user", "assistant", "tool_call"})
DIFF_CARD_OMIT = ("hunks", "original_content", "current_content", "baseline_content")
TOOL_CALL_META_KEYS = ("success", "tool_call_id")


def select_history_page(rows: list[dict], *, before_sort_order: int | None, limit: int) -> tuple[list[dict], bool]:
    """从末尾取 limit 条可见消息。页首若落在连续 tool_call 中，则补齐这一整组。"""
    ordered = [row for row in rows if row.get("role") in VISIBLE_ROLES]
    ordered.sort(key=lambda row: row["sort_order"])
    if before_sort_order is not None:
        ordered = [row for row in ordered if row["sort_order"] < before_sort_order]
    if not ordered:
        return [], False
    start = max(0, len(ordered) - limit)
    while (
        start > 0
        and ordered[start]["role"] == "tool_call"
        and ordered[start - 1]["role"] == "tool_call"
    ):
        start -= 1
    return ordered[start:], start > 0


def slim_history_message(message: dict) -> dict:
    """去掉时间线用不到的工具参数、思考过程和 diff 全文。"""
    meta = dict(message.get("meta") or {})
    if message.get("role") == "tool_call":
        meta = {key: meta[key] for key in TOOL_CALL_META_KEYS if key in meta}
    elif meta.get("type") == "chapter_content_diff_card":
        card = dict(meta.get("chapterContentDiffCard") or {})
        for key in DIFF_CARD_OMIT:
            card.pop(key, None)
        meta["chapterContentDiffCard"] = card
    slimmed = dict(message)
    slimmed["meta"] = meta
    return slimmed


def list_history_page(session_id: str, *, before_sort_order: int | None = None, limit: int = HISTORY_PAGE_VISIBLE_LIMIT) -> dict:
    from services.session_store import session_store

    db = session_store._get_db()
    try:
        index_rows = (
            db.query(SupervisorMessage.id, SupervisorMessage.role, SupervisorMessage.sort_order)
            .filter(SupervisorMessage.session_id == session_id)
            .order_by(SupervisorMessage.sort_order)
            .all()
        )
        index = [{"id": row.id, "role": row.role, "sort_order": row.sort_order} for row in index_rows]
        page, has_more = select_history_page(index, before_sort_order=before_sort_order, limit=limit)
        ids = [row["id"] for row in page]
        if not ids:
            return {"messages": [], "has_more": False}
        full_rows = db.query(SupervisorMessage).filter(SupervisorMessage.id.in_(ids)).all()
        by_id = {row.id: row for row in full_rows}
        messages = [slim_history_message(session_store._message_to_dict(by_id[row_id])) for row_id in ids]
        messages = _sync_latest_todolist(db, session_id, messages)
        return {"messages": messages, "has_more": has_more}
    finally:
        db.close()


def get_diff_hunks(session_id: str, message_id: str) -> dict | None:
    from services.session_store import session_store

    db = session_store._get_db()
    try:
        message = db.get(SupervisorMessage, message_id)
        if message is None or message.session_id != session_id:
            return None
        meta = message.meta or {}
        if meta.get("type") != "chapter_content_diff_card":
            return None
        card = meta.get("chapterContentDiffCard") or {}
        return {"hunks": card.get("hunks") or []}
    finally:
        db.close()


def _sync_latest_todolist(db, session_id: str, messages: list[dict]) -> list[dict]:
    latest = (
        db.query(SupervisorMessage.id)
        .filter(SupervisorMessage.session_id == session_id)
        .filter(SupervisorMessage.role == "assistant")
        .filter(SupervisorMessage.meta.op("->>")("type") == "requirements_todolist")
        .order_by(SupervisorMessage.sort_order.desc())
        .first()
    )
    if latest is None or all(message["id"] != latest[0] for message in messages):
        return messages
    from services.supervisor_event_persist import enrich_messages_with_todolist

    return enrich_messages_with_todolist(db, session_id, messages)
