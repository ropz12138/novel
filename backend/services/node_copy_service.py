"""复制节点与章节引用的角色到另一部作品，保留正文和章节笔记。"""
import copy
import uuid
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.chapter import Chapter
from models.edge import Edge
from models.node import Node
from services.node_content_write_service import write_node_content


@dataclass
class NodeCopyResult:
    nodes: list[Node]
    edges: list[Edge]
    omitted_character_refs: list[str]


def copy_node_to_work(db: Session, source: Node, target_work_id: str) -> NodeCopyResult:
    source_nodes = db.query(Node).filter(Node.work_id == source.work_id).all()
    nodes_by_id = {node.id: node for node in source_nodes}
    structural = [source]
    characters, omitted = _referenced_characters(structural, nodes_by_id)
    copied_sources = structural + characters
    id_map = {node.id: str(uuid.uuid4()) for node in copied_sources}
    character_sort = _character_sort_orders(db, target_work_id, characters)
    root_sort = _next_sort_order(db, target_work_id, source.type)

    created_pairs = []
    created_nodes = []
    for source_node in copied_sources:
        sort_order = root_sort if source_node.id == source.id else character_sort[source_node.id]
        created = Node(
            id=id_map[source_node.id],
            work_id=target_work_id,
            type=source_node.type,
            title=source_node.title,
            content="",
            extra_data=_remap_extra(source_node.extra_data, id_map),
            layer=source_node.layer,
            sort_order=sort_order,
            scope=source_node.scope,
            position_x=0.0,
            position_y=0.0,
            locked=False,
        )
        created_pairs.append((source_node, created))
        created_nodes.append(created)
    db.add_all(created_nodes)
    db.flush()

    notes_by_id = _chapter_notes(db, [node.id for node in structural if node.type == "chapter"])
    for source_node, created in created_pairs:
        summary = notes_by_id.get(source_node.id, "") if created.type == "chapter" else None
        write_node_content(db, created, source_node.content or "", summary=summary)

    db.commit()
    for item in created_nodes:
        db.refresh(item)
    return NodeCopyResult(
        nodes=created_nodes,
        edges=[],
        omitted_character_refs=omitted,
    )


def _referenced_characters(structural, nodes_by_id):
    characters = []
    omitted = []
    seen = set()
    for node in structural:
        if node.type != "chapter":
            continue
        raw = (node.extra_data or {}).get("characters")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            character_id = item["id"]
            if character_id in seen:
                continue
            seen.add(character_id)
            character = nodes_by_id.get(character_id)
            if character is None or character.type != "character":
                omitted.append(character_id)
                continue
            characters.append(character)
    return characters, omitted


def _remap_extra(extra, id_map):
    data = copy.deepcopy(extra or {})
    data.pop("chapter_elements", None)
    characters = data.get("characters")
    if not isinstance(characters, list):
        return data
    remapped = []
    for item in characters:
        if not isinstance(item, dict) or not item.get("id"):
            remapped.append(item)
            continue
        new_id = id_map.get(item["id"])
        if new_id is None:
            continue
        remapped.append({**item, "id": new_id})
    data["characters"] = remapped
    return data


def _chapter_notes(db, chapter_ids):
    if not chapter_ids:
        return {}
    rows = db.query(Chapter).filter(Chapter.node_id.in_(chapter_ids)).all()
    return {row.node_id: row.notes or "" for row in rows}


def _next_sort_order(db, work_id, node_type):
    current = db.query(func.max(Node.sort_order)).filter(
        Node.work_id == work_id,
        Node.type == node_type,
    ).scalar()
    return int(current or 0) + 1


def _character_sort_orders(db, work_id, characters):
    if not characters:
        return {}
    start = _next_sort_order(db, work_id, "character")
    ordered = sorted(characters, key=lambda node: (node.sort_order, node.id))
    return {node.id: start + index for index, node in enumerate(ordered)}
