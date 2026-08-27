"""章节顺序、前序上下文与评估提示词组装。"""
from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from models.chapter import Chapter
from models.node import Node


def chapter_order_key(node: Node) -> tuple:
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

RECENT_FULL_HISTORY_LIMIT = 5

CHARACTER_SCOPE_LABELS = {
    "global": "主角",
    "major": "主要配角",
    "minor": "次要配角",
    "temp": "临时",
}

_EVALUATE_LATEST_CHAPTER_INSTRUCTION = """你是一位资深网文读者。请结合上一条消息中的前序章节信息，阅读本章全文，从读者视角评估本章。

评估需涵盖：情节逻辑是否通顺、人物行为是否合理、与前文是否衔接、文笔与可读性、节奏与代入感等；明确指出具体问题和可取之处。

请严格输出 JSON（不要 markdown 代码块），包含两个字段：
{
  "evaluation": "详细评估结果，例如哪里逻辑不通、哪里文笔不好",
  "chapter_overview": "将该章压缩成很简短的摘要信息（100字以内）"
}"""


def list_ordered_chapters(db, work_id: str) -> list[Node]:
    chapters = db.query(Node).filter(
        Node.work_id == work_id,
        Node.type == "chapter",
    ).all()
    chapters.sort(key=chapter_order_key)
    return chapters


def get_chapter_summary(db, node: Node) -> str:
    chapter = db.query(Chapter).filter(Chapter.node_id == node.id).first()
    if chapter and chapter.summary:
        return chapter.summary.strip()
    return ""


def clear_chapter_summary_on_content_change(db, node: Node) -> None:
    """章节正文变更后清空旧评估摘要，避免与新正文不一致。"""
    if node.type != "chapter":
        return
    chapter = db.query(Chapter).filter(Chapter.node_id == node.id).first()
    if chapter is not None:
        chapter.summary = ""


def format_characters_system_message(db, work_id: str) -> str:
    characters = db.query(Node).filter(
        Node.work_id == work_id,
        Node.type == "character",
    ).all()
    if not characters:
        return "（暂无角色设定）"
    parts = ["## 角色设定"]
    for character in characters:
        scope = CHARACTER_SCOPE_LABELS.get(character.scope or "minor", character.scope or "minor")
        parts.append(f"\n### {character.title}（{scope}）\n{character.content or ''}")
    return "\n".join(parts)


def build_history_user_message(
    db,
    work_id: str,
    latest_chapter_id: str,
    recent_full_limit: int = RECENT_FULL_HISTORY_LIMIT,
) -> str:
    chapters = list_ordered_chapters(db, work_id)
    current_index = next(
        (index for index, chapter in enumerate(chapters) if chapter.id == latest_chapter_id),
        None,
    )
    if current_index is None:
        raise ValueError("章节节点不存在")
    history = chapters[:current_index]
    if not history:
        return "（无前序章节）"

    split_at = max(0, len(history) - recent_full_limit)
    older = history[:split_at]
    recent = history[split_at:]
    sections: list[str] = []

    if older:
        sections.append("======= 更早章节概览 =======")
        for chapter in older:
            summary = get_chapter_summary(db, chapter) or "（暂无概览）"
            sections.append(f"【{chapter.title}】\n{summary}")

    if recent:
        sections.append("======= 近几章正文（全文） =======")
        for chapter in recent:
            sections.append(f"【{chapter.title}】\n{chapter.content or '（空）'}")

    return "\n\n".join(sections)


def build_latest_chapter_user_message(chapter: Node) -> str:
    return (
        "======= 待评估的最新章节（全文） =======\n"
        f"【{chapter.title}】\n{chapter.content or ''}\n"
        "=====================================\n\n"
        f"{_EVALUATE_LATEST_CHAPTER_INSTRUCTION}"
    )


def build_evaluate_chapter_messages(db, work_id: str, chapter: Node) -> list:
    return [
        SystemMessage(content=format_characters_system_message(db, work_id)),
        HumanMessage(content=build_history_user_message(db, work_id, chapter.id)),
        HumanMessage(content=build_latest_chapter_user_message(chapter)),
    ]


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
