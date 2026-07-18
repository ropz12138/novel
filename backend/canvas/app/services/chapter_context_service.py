"""Build authoritative, database-backed context for chapter writing."""
from __future__ import annotations

import json
import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.edge import Edge
from app.models.node import Node


def _chapter_order_key(node: Node) -> tuple:
    extra = node.extra_data or {}
    for key in ("chapter_number", "chapter_index", "order", "sequence"):
        value = extra.get(key)
        if isinstance(value, (int, float)):
            return (0, float(value), node.created_at or 0)
        if isinstance(value, str) and value.strip().isdigit():
            return (0, float(value.strip()), node.created_at or 0)
    match = re.search(r"第\s*(\d+)\s*章", node.title or "")
    if match:
        return (0, float(match.group(1)), node.created_at or 0)
    return (1, node.layer or 0, node.position_x or 0, node.created_at or 0)


def _node_item(node: Node) -> dict:
    return {
        "id": node.id,
        "type": node.type,
        "title": node.title,
        "content": node.content or "",
        "extra_data": node.extra_data or {},
        "layer": node.layer,
    }


def _edge_item(edge: Edge, nodes: dict[str, Node], chapter_id: str) -> dict:
    source = nodes.get(edge.source_id)
    target = nodes.get(edge.target_id)
    return {
        "id": edge.id,
        "source_id": edge.source_id,
        "source_type": source.type if source else None,
        "source_title": source.title if source else "未知",
        "target_id": edge.target_id,
        "target_type": target.type if target else None,
        "target_title": target.title if target else "未知",
        "direction": "out" if edge.source_id == chapter_id else "in",
        "edge_type": edge.edge_type,
        "label": edge.label or "",
        "extra_data": edge.extra_data or {},
    }


def build_authoritative_chapter_context(
    db: Session,
    chapter_node_id: str,
    *,
    previous_limit: int = 3,
    next_limit: int = 2,
) -> dict:
    chapter = db.query(Node).filter(Node.id == chapter_node_id).first()
    if not chapter or chapter.type != "chapter":
        raise ValueError("章节节点不存在")

    direct_edges = db.query(Edge).filter(
        Edge.work_id == chapter.work_id,
        or_(Edge.source_id == chapter.id, Edge.target_id == chapter.id),
    ).all()
    endpoint_ids = {
        node_id for edge in direct_edges for node_id in (edge.source_id, edge.target_id)
    }
    direct_nodes = {
        node.id: node
        for node in db.query(Node).filter(Node.id.in_(endpoint_ids)).all()
    } if endpoint_ids else {chapter.id: chapter}

    chapters = db.query(Node).filter(
        Node.work_id == chapter.work_id,
        Node.type == "chapter",
    ).all()
    chapters.sort(key=_chapter_order_key)
    current_index = next(
        (index for index, item in enumerate(chapters) if item.id == chapter.id), 0
    )
    previous = chapters[max(0, current_index - previous_limit):current_index]
    future = chapters[current_index + 1:current_index + 1 + next_limit]

    future_ids = {node.id for node in future}
    future_edges = db.query(Edge).filter(
        Edge.work_id == chapter.work_id,
        or_(Edge.source_id.in_(future_ids), Edge.target_id.in_(future_ids)),
    ).all() if future_ids else []
    future_endpoint_ids = {
        node_id for edge in future_edges for node_id in (edge.source_id, edge.target_id)
    }
    future_node_map = {
        node.id: node
        for node in db.query(Node).filter(Node.id.in_(future_endpoint_ids)).all()
    } if future_endpoint_ids else {}
    next_chapter_plans = []
    for future_chapter in future:
        relations = [
            _edge_item(edge, future_node_map, future_chapter.id)
            for edge in future_edges
            if edge.source_id == future_chapter.id or edge.target_id == future_chapter.id
        ]
        related_ids = {
            edge.source_id if edge.target_id == future_chapter.id else edge.target_id
            for edge in future_edges
            if edge.source_id == future_chapter.id or edge.target_id == future_chapter.id
        }
        next_chapter_plans.append({
            "chapter": _node_item(future_chapter),
            "relations": relations,
            "related_nodes": [
                _node_item(future_node_map[node_id])
                for node_id in related_ids
                if node_id in future_node_map and node_id != future_chapter.id
            ],
        })

    return {
        "chapter": _node_item(chapter),
        "chapter_relations": [
            _edge_item(edge, direct_nodes, chapter.id) for edge in direct_edges
        ],
        "related_nodes": [
            _node_item(node)
            for node_id, node in direct_nodes.items()
            if node_id != chapter.id
        ],
        "previous_chapters": [_node_item(node) for node in previous],
        "next_chapter_plans": next_chapter_plans,
    }


def format_authoritative_chapter_context(
    context: dict,
    supervisor_notes: str = "",
) -> str:
    payload = dict(context)
    payload["supervisor_notes"] = supervisor_notes or ""
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
