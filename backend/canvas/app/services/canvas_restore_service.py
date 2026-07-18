"""画布恢复 — 将 work 恢复到 CanvasSnapshot 状态。"""
from sqlalchemy.orm import Session

from app.models.node import Node
from app.models.edge import Edge
from app.models.character_relation import CharacterRelation
from app.schemas.canvas_snapshot import CanvasSnapshot, CanvasRestoreResponse


def apply_canvas_snapshot(db: Session, work_id: str, snapshot: CanvasSnapshot) -> CanvasRestoreResponse:
    """将画布恢复到 snapshot 状态（增删改节点/边/角色关系）。"""
    snap_node_ids = {n.id for n in snapshot.nodes}
    snap_edge_ids = {e.id for e in snapshot.edges}
    snap_relation_ids = {r.id for r in snapshot.character_relations}

    existing_nodes = {
        n.id: n for n in db.query(Node).filter(Node.work_id == work_id).all()
    }
    existing_edges = {
        e.id: e for e in db.query(Edge).filter(Edge.work_id == work_id).all()
    }
    existing_relations = {
        r.id: r
        for r in db.query(CharacterRelation).filter(CharacterRelation.work_id == work_id).all()
    }

    for relation_id, relation in existing_relations.items():
        if relation_id not in snap_relation_ids:
            db.delete(relation)

    for edge_id, edge in existing_edges.items():
        if edge_id not in snap_edge_ids:
            db.delete(edge)

    for node_id, node in existing_nodes.items():
        if node_id not in snap_node_ids:
            db.delete(node)

    for snap_node in snapshot.nodes:
        existing = existing_nodes.get(snap_node.id)
        if existing:
            existing.type = snap_node.type
            existing.layer = snap_node.layer
            existing.scope = snap_node.scope
            existing.title = snap_node.title
            existing.content = snap_node.content
            existing.extra_data = snap_node.extra_data
            existing.position_x = snap_node.position_x
            existing.position_y = snap_node.position_y
        else:
            db.add(Node(
                id=snap_node.id,
                work_id=work_id,
                type=snap_node.type,
                layer=snap_node.layer,
                scope=snap_node.scope,
                title=snap_node.title,
                content=snap_node.content,
                extra_data=snap_node.extra_data,
                position_x=snap_node.position_x,
                position_y=snap_node.position_y,
            ))

    for snap_edge in snapshot.edges:
        existing = existing_edges.get(snap_edge.id)
        if existing:
            existing.source_id = snap_edge.source_id
            existing.target_id = snap_edge.target_id
            existing.edge_type = snap_edge.edge_type
            existing.label = snap_edge.label
            existing.extra_data = snap_edge.extra_data
        else:
            db.add(Edge(
                id=snap_edge.id,
                work_id=work_id,
                source_id=snap_edge.source_id,
                target_id=snap_edge.target_id,
                edge_type=snap_edge.edge_type,
                label=snap_edge.label,
                extra_data=snap_edge.extra_data,
            ))

    for snap_relation in snapshot.character_relations:
        existing = existing_relations.get(snap_relation.id)
        if existing:
            existing.source_id = snap_relation.source_id
            existing.target_id = snap_relation.target_id
            existing.relation_type = snap_relation.relation_type
            existing.label = snap_relation.label
        else:
            db.add(CharacterRelation(
                id=snap_relation.id,
                work_id=work_id,
                source_id=snap_relation.source_id,
                target_id=snap_relation.target_id,
                relation_type=snap_relation.relation_type,
                label=snap_relation.label,
            ))

    db.commit()

    return CanvasRestoreResponse(
        success=True,
        node_count=len(snapshot.nodes),
        edge_count=len(snapshot.edges),
        relation_count=len(snapshot.character_relations),
    )
