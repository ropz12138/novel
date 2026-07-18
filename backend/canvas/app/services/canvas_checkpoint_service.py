"""画布 checkpoint — 捕获与恢复。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.node import Node
from app.models.edge import Edge
from app.models.character_relation import CharacterRelation
from app.models.session import SupervisorMessage
from app.models.canvas_checkpoint import (
    CanvasCheckpoint,
    CanvasCheckpointNode,
    CanvasCheckpointEdge,
    CanvasCheckpointRelation,
)
from app.schemas.canvas_snapshot import (
    CanvasSnapshot,
    SnapshotNode,
    SnapshotEdge,
    SnapshotCharacterRelation,
)
from app.services.canvas_restore_service import apply_canvas_snapshot


def _work_to_snapshot(db: Session, work_id: str) -> CanvasSnapshot:
    nodes = db.query(Node).filter(Node.work_id == work_id).all()
    edges = db.query(Edge).filter(Edge.work_id == work_id).all()
    relations = db.query(CharacterRelation).filter(CharacterRelation.work_id == work_id).all()
    return CanvasSnapshot(
        nodes=[
            SnapshotNode(
                id=n.id,
                type=n.type,
                title=n.title,
                content=n.content or "",
                extra_data=n.extra_data or {},
                layer=n.layer,
                scope=n.scope,
                position_x=n.position_x,
                position_y=n.position_y,
            )
            for n in nodes
        ],
        edges=[
            SnapshotEdge(
                id=e.id,
                source_id=e.source_id,
                target_id=e.target_id,
                edge_type=e.edge_type,
                label=e.label or "",
                extra_data=e.extra_data or {},
            )
            for e in edges
        ],
        character_relations=[
            SnapshotCharacterRelation(
                id=r.id,
                source_id=r.source_id,
                target_id=r.target_id,
                relation_type=r.relation_type,
                label=r.label or "",
            )
            for r in relations
        ],
    )


def capture_canvas_checkpoint(
    db: Session,
    *,
    session_id: str,
    work_id: str,
    trigger_message_id: str,
    sort_order: int,
) -> CanvasCheckpoint:
    """在 Agent 执行前捕获当前画布快照。"""
    snapshot = _work_to_snapshot(db, work_id)

    checkpoint = CanvasCheckpoint(
        session_id=session_id,
        work_id=work_id,
        trigger_message_id=trigger_message_id,
        sort_order=sort_order,
        node_count=len(snapshot.nodes),
        edge_count=len(snapshot.edges),
        relation_count=len(snapshot.character_relations),
    )
    db.add(checkpoint)
    db.flush()

    for n in snapshot.nodes:
        db.add(CanvasCheckpointNode(
            checkpoint_id=checkpoint.id,
            node_id=n.id,
            type=n.type,
            title=n.title,
            content=n.content,
            extra_data=n.extra_data,
            layer=n.layer,
            scope=n.scope,
            position_x=n.position_x,
            position_y=n.position_y,
        ))

    for e in snapshot.edges:
        db.add(CanvasCheckpointEdge(
            checkpoint_id=checkpoint.id,
            edge_id=e.id,
            source_id=e.source_id,
            target_id=e.target_id,
            edge_type=e.edge_type,
            label=e.label,
            extra_data=e.extra_data,
        ))

    for r in snapshot.character_relations:
        db.add(CanvasCheckpointRelation(
            checkpoint_id=checkpoint.id,
            relation_id=r.id,
            source_id=r.source_id,
            target_id=r.target_id,
            relation_type=r.relation_type,
            label=r.label,
        ))

    db.commit()
    db.refresh(checkpoint)
    return checkpoint


def checkpoint_to_snapshot(db: Session, checkpoint_id: str) -> CanvasSnapshot:
    cp = db.query(CanvasCheckpoint).filter_by(id=checkpoint_id).first()
    if not cp:
        raise ValueError(f"checkpoint not found: {checkpoint_id}")

    return CanvasSnapshot(
        nodes=[
            SnapshotNode(
                id=n.node_id,
                type=n.type,
                title=n.title,
                content=n.content or "",
                extra_data=n.extra_data or {},
                layer=n.layer,
                scope=n.scope,
                position_x=n.position_x,
                position_y=n.position_y,
            )
            for n in cp.nodes
        ],
        edges=[
            SnapshotEdge(
                id=e.edge_id,
                source_id=e.source_id,
                target_id=e.target_id,
                edge_type=e.edge_type,
                label=e.label or "",
                extra_data=e.extra_data or {},
            )
            for e in cp.edges
        ],
        character_relations=[
            SnapshotCharacterRelation(
                id=r.relation_id,
                source_id=r.source_id,
                target_id=r.target_id,
                relation_type=r.relation_type,
                label=r.label or "",
            )
            for r in cp.character_relations
        ],
    )


def restore_canvas_from_checkpoint(db: Session, work_id: str, checkpoint_id: str):
    snapshot = checkpoint_to_snapshot(db, checkpoint_id)
    return apply_canvas_snapshot(db, work_id, snapshot)


def get_checkpoint_for_message(db: Session, trigger_message_id: str) -> CanvasCheckpoint | None:
    return (
        db.query(CanvasCheckpoint)
        .filter_by(trigger_message_id=trigger_message_id)
        .first()
    )


def truncate_messages_from(db: Session, session_id: str, from_sort_order: int) -> None:
    """删除 sort_order >= from_sort_order 的消息（checkpoint 随 message CASCADE）。"""
    (
        db.query(SupervisorMessage)
        .filter(
            SupervisorMessage.session_id == session_id,
            SupervisorMessage.sort_order >= from_sort_order,
        )
        .delete(synchronize_session=False)
    )
    db.commit()


def prepare_edit_resend(
    db: Session,
    *,
    session_id: str,
    work_id: str,
    message_id: str,
    new_content: str,
) -> dict:
    """编辑重发：恢复到该用户消息执行前的画布，截断对话尾巴，写入新用户消息并拍快照。"""
    msg = (
        db.query(SupervisorMessage)
        .filter_by(id=message_id, session_id=session_id)
        .first()
    )
    if not msg:
        raise ValueError("message not found")
    if msg.role != "user":
        raise ValueError("only user messages can be edited")

    checkpoint = get_checkpoint_for_message(db, message_id)
    if not checkpoint:
        raise ValueError("checkpoint not found for message")

    restore_canvas_from_checkpoint(db, work_id, checkpoint.id)
    truncate_messages_from(db, session_id, msg.sort_order)

    max_order = (
        db.query(SupervisorMessage.sort_order)
        .filter_by(session_id=session_id)
        .order_by(SupervisorMessage.sort_order.desc())
        .first()
    )
    next_order = (max_order[0] + 1) if max_order else 0

    new_msg = SupervisorMessage(
        session_id=session_id,
        role="user",
        content=new_content,
        work_id=work_id,
        sort_order=next_order,
    )
    db.add(new_msg)
    db.commit()
    db.refresh(new_msg)

    capture_canvas_checkpoint(
        db,
        session_id=session_id,
        work_id=work_id,
        trigger_message_id=new_msg.id,
        sort_order=new_msg.sort_order,
    )

    return {
        "id": new_msg.id,
        "session_id": new_msg.session_id,
        "role": new_msg.role,
        "content": new_msg.content,
        "meta": new_msg.meta or {},
        "sort_order": new_msg.sort_order,
    }
