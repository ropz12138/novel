"""按画布层级生成作品内稳定的动态章节目录。"""
from __future__ import annotations

import hashlib
import json

from models.edge import Edge
from models.node import Node

HIERARCHY = {"outline": "volume", "volume": "plot", "plot": "chapter"}


def build_chapter_catalog(db, work_id: str) -> tuple[list[Node], str, list[dict]]:
    nodes = db.query(Node).filter(Node.work_id == work_id).all()
    by_id = {node.id: node for node in nodes}
    children: dict[str, list[Node]] = {}
    parent_by_child: dict[str, str] = {}
    issues: list[dict] = []
    edges = db.query(Edge).filter(Edge.work_id == work_id).all()
    hierarchy_edges = []
    for edge in edges:
        source, target = by_id.get(edge.source_id), by_id.get(edge.target_id)
        if not source or not target or HIERARCHY.get(source.type) != target.type:
            continue
        hierarchy_edges.append(edge)
        if target.id in parent_by_child and parent_by_child[target.id] != source.id:
            issues.append({"code": "multiple_parents", "node_id": target.id})
            continue
        parent_by_child[target.id] = source.id
        children.setdefault(source.id, []).append(target)

    for rows in children.values():
        rows.sort(key=lambda node: (node.sort_order, node.id))

    ordered: list[Node] = []
    seen: set[str] = set()

    def visit(node: Node):
        if node.id in seen:
            return
        seen.add(node.id)
        if node.type == "chapter":
            ordered.append(node)
            return
        for child in children.get(node.id, []):
            visit(child)

    roots = sorted((n for n in nodes if n.type == "outline" and n.id not in parent_by_child),
                   key=lambda node: (node.sort_order, node.id))
    for root in roots:
        visit(root)

    for chapter in sorted((n for n in nodes if n.type == "chapter" and n.id not in seen),
                          key=lambda node: (node.sort_order, node.id)):
        issues.append({"code": "orphan_chapter", "node_id": chapter.id})

    revision_rows = [
        {"id": node.id, "type": node.type, "sort_order": node.sort_order,
         "parent_id": parent_by_child.get(node.id)}
        for node in sorted(nodes, key=lambda item: item.id)
        if node.type in HIERARCHY or node.type == "chapter"
    ]
    revision = hashlib.sha256(json.dumps(revision_rows, ensure_ascii=False,
                                         sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ordered, revision, issues
