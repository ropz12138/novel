"""进行中的工具视为一个整体：未完成则丢弃该次执行的全部副作用。"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from models.chapter import Chapter
from models.node import Node
from models.session import SupervisorMessage
from models.todo_item import TodoItem
from models.workflow import WorkflowArtifact
from services.canvas_checkpoint_service import _work_to_snapshot
from services.canvas_restore_service import apply_canvas_snapshot
from services.node_content_write_service import write_node_content

logger = logging.getLogger(__name__)


def _get_db() -> Session:
    from database import SessionLocal
    return SessionLocal()


def _max_message_sort_order(db: Session, session_id: str | None) -> int:
    if not session_id:
        return -1
    row = (
        db.query(SupervisorMessage.sort_order)
        .filter_by(session_id=session_id)
        .order_by(SupervisorMessage.sort_order.desc())
        .first()
    )
    return row[0] if row else -1


def _todo_rows(db: Session, session_id: str | None) -> list[dict]:
    if not session_id:
        return []
    items = (
        db.query(TodoItem)
        .filter_by(session_id=session_id)
        .order_by(TodoItem.sort_order.asc(), TodoItem.created_at.asc())
        .all()
    )
    return [
        {
            "id": item.id,
            "task_id": item.task_id,
            "task": item.task,
            "status": item.status,
            "sort_order": item.sort_order,
        }
        for item in items
    ]


def _artifact_ids(db: Session, work_id: str | None) -> set[str]:
    if not work_id:
        return set()
    rows = db.query(WorkflowArtifact.id).filter(WorkflowArtifact.work_id == work_id).all()
    return {row[0] for row in rows}


def _sync_chapters_from_nodes(db: Session, work_id: str) -> None:
    chapter_nodes = db.query(Node).filter(Node.work_id == work_id, Node.type == "chapter").all()
    node_ids = {node.id for node in chapter_nodes}
    for node in chapter_nodes:
        write_node_content(db, node, node.content or "")
    orphans = db.query(Chapter).filter(Chapter.work_id == work_id).all()
    for chapter in orphans:
        if chapter.node_id not in node_ids:
            db.delete(chapter)


def _restore_todos(db: Session, session_id: str | None, rows: list[dict]) -> None:
    if not session_id:
        return
    db.query(TodoItem).filter_by(session_id=session_id).delete(synchronize_session=False)
    db.flush()
    for row in rows:
        db.add(TodoItem(
            id=row["id"],
            session_id=session_id,
            task_id=row["task_id"],
            task=row["task"],
            status=row["status"],
            sort_order=row["sort_order"],
        ))


@dataclass
class ToolExecutionUnit:
    work_id: str | None
    session_id: str | None
    tool_call_id: str
    canvas_snapshot: object | None
    artifact_ids: set[str] = field(default_factory=set)
    todo_rows: list[dict] = field(default_factory=list)
    message_sort_watermark: int = -1

    @classmethod
    def begin(
        cls,
        *,
        work_id: str | None,
        session_id: str | None,
        tool_call_id: str,
    ) -> "ToolExecutionUnit":
        db = _get_db()
        try:
            snapshot = copy.deepcopy(_work_to_snapshot(db, work_id)) if work_id else None
            return cls(
                work_id=work_id,
                session_id=session_id,
                tool_call_id=tool_call_id,
                canvas_snapshot=snapshot,
                artifact_ids=_artifact_ids(db, work_id),
                todo_rows=_todo_rows(db, session_id),
                message_sort_watermark=_max_message_sort_order(db, session_id),
            )
        finally:
            db.close()

    def rollback(self) -> None:
        db = _get_db()
        try:
            if self.work_id and self.canvas_snapshot is not None:
                apply_canvas_snapshot(db, self.work_id, self.canvas_snapshot)
                _sync_chapters_from_nodes(db, self.work_id)
                artifacts = db.query(WorkflowArtifact).filter(
                    WorkflowArtifact.work_id == self.work_id
                ).all()
                for artifact in artifacts:
                    if artifact.id not in self.artifact_ids:
                        db.delete(artifact)
            _restore_todos(db, self.session_id, self.todo_rows)
            if self.session_id:
                (
                    db.query(SupervisorMessage)
                    .filter(
                        SupervisorMessage.session_id == self.session_id,
                        SupervisorMessage.sort_order > self.message_sort_watermark,
                    )
                    .delete(synchronize_session=False)
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        logger.info(
            "rolled back in-flight tool work_id=%s session_id=%s tool_call_id=%s",
            self.work_id,
            self.session_id,
            self.tool_call_id,
        )


def rollback_active_tool_unit() -> None:
    from services.agents.supervisor import get_context

    ctx = get_context()
    unit = ctx.get("active_tool_unit")
    if unit is None:
        return
    unit.rollback()
    ctx["active_tool_unit"] = None


async def run_atomic_tool_calls(
    *,
    tool_node,
    state: dict,
    work_id: str | None,
    session_id: str | None,
) -> dict:
    """按工具串行执行；每个工具开始时拍快照，未完成则整笔回滚。"""
    from services.agents.supervisor import get_context
    from services.message_content_utils import extract_text_content

    last = state["messages"][-1]
    tool_calls = list(getattr(last, "tool_calls", None) or [])
    if not tool_calls:
        return {"messages": []}

    collected = []
    ctx = get_context()
    for call in tool_calls:
        unit = ToolExecutionUnit.begin(
            work_id=work_id,
            session_id=session_id,
            tool_call_id=str(call.get("id") or ""),
        )
        ctx["active_tool_unit"] = unit
        partial = AIMessage(
            content=extract_text_content(getattr(last, "content", "")),
            tool_calls=[call],
        )
        try:
            out = await tool_node.ainvoke({"messages": [partial]})
        except BaseException:
            raise
        collected.extend(out.get("messages") or [])
        if ctx.get("active_tool_unit") is unit:
            ctx["active_tool_unit"] = None
    return {"messages": collected}
