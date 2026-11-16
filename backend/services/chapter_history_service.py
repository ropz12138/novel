"""章节顺序。字数统计按 sort_order 定位章节。"""
from __future__ import annotations

from sqlalchemy.orm import selectinload

from models.node import Node


def chapter_order_key(node: Node) -> tuple:
    """章节排序键。

    顺序只认 sort_order：它是创建时必填的字段。此前从 extra_data 序号、标题
    「第N章」正则与坐标逐级推断，同一份顺序因此有多个来源，彼此可能矛盾。
    node.id 只作为并列时的确定性 tie-breaker，保证两次排序结果一致。
    """
    return (node.sort_order, node.id or "")


def list_ordered_chapters(db, work_id: str) -> list[Node]:
    chapters = db.query(Node).options(selectinload(Node.chapter_record)).filter(
        Node.work_id == work_id,
        Node.type == "chapter",
    ).all()
    chapters.sort(key=chapter_order_key)
    return chapters


def resolve_chapter_for_evaluation(
    db,
    work_id: str,
    chapter_node_id: str | None = None,
) -> Node:
    chapters = list_ordered_chapters(db, work_id)
    if not chapters:
        raise ValueError("作品中没有章节节点")

    if chapter_node_id:
        chapter = next((item for item in chapters if item.id == chapter_node_id), None)
        if not chapter:
            raise ValueError("章节节点不存在")
        return chapter

    for chapter in reversed(chapters):
        if chapter.content:
            return chapter
    raise ValueError("没有可评估的正文章节")
