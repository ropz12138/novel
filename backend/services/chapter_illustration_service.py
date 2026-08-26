"""章节插画生成与正文插入服务。"""
from __future__ import annotations

import re
from pathlib import Path
import uuid

from sqlalchemy.orm import Session

from config import PROJECT_ROOT, settings
from models.node import Node
from models.chapter_illustration import ChapterIllustration
from utils.text2image import generate_and_save, get_api_key

ILLUSTRATIONS_DIR = PROJECT_ROOT / "data" / "illustrations"

CHAPTER_ILLUSTRATION_STYLE_SUFFIX = "小说章节插画，横构图，高清，细节丰富。"

_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]")


def validate_chinese_prompt(prompt: str) -> None:
    """生图提示词必须使用中文。"""
    if not _CJK_PATTERN.search(prompt):
        raise ValueError("生图提示词必须使用中文，请用中文描述场景、人物、动作与氛围")


def build_illustration_markdown(illustration_id: str) -> str:
    return f"![章节插画](/api/illustrations/{illustration_id})"


def split_paragraphs(content: str) -> list[str]:
    text = content.strip()
    if not text:
        return []
    return text.split("\n\n")


def validate_insert_after_paragraph(insert_after_paragraph: int) -> None:
    """插图必须插在相关剧情段落之后，读者先读文字再看图。"""
    if insert_after_paragraph == 0:
        raise ValueError(
            "插图必须插在相关剧情段落之后（insert_after_paragraph>=1），"
            "禁止插在正文最前，避免读者在未读剧情时先看到图片"
        )


def insert_illustration_into_content(
    content: str,
    insert_after_paragraph: int,
    markdown_line: str,
) -> str:
    if insert_after_paragraph == -1:
        if not content.strip():
            return markdown_line
        return content.rstrip() + "\n\n" + markdown_line

    validate_insert_after_paragraph(insert_after_paragraph)

    paragraphs = split_paragraphs(content)
    if insert_after_paragraph > len(paragraphs):
        raise ValueError(
            f"insert_after_paragraph={insert_after_paragraph} 超出段落数 {len(paragraphs)}"
        )

    before = paragraphs[:insert_after_paragraph]
    after = paragraphs[insert_after_paragraph:]
    parts: list[str] = []
    if before:
        parts.append("\n\n".join(before))
    parts.append(markdown_line)
    if after:
        parts.append("\n\n".join(after))
    return "\n\n".join(parts)


def build_full_prompt(user_prompt: str) -> str:
    prompt = user_prompt.strip()
    if not prompt:
        raise ValueError("生图提示词不能为空")
    validate_chinese_prompt(prompt)
    return f"{prompt}，{CHAPTER_ILLUSTRATION_STYLE_SUFFIX}"


def illustration_file_path(work_id: str, illustration_id: str) -> Path:
    return ILLUSTRATIONS_DIR / work_id / f"{illustration_id}.png"


def create_chapter_illustration(
    db: Session,
    work_id: str,
    chapter_node_id: str,
    prompt: str,
    insert_after_paragraph: int,
) -> ChapterIllustration:
    node = db.query(Node).filter(
        Node.id == chapter_node_id,
        Node.work_id == work_id,
    ).first()
    if not node:
        raise ValueError("章节节点不存在")
    if node.type != "chapter":
        raise ValueError("仅 chapter 类型节点可插入插画")
    if not (node.content or "").strip():
        raise ValueError("章节正文为空，无法插入插画")

    validate_insert_after_paragraph(insert_after_paragraph)

    full_prompt = build_full_prompt(prompt)
    illustration_id = str(uuid.uuid4())
    save_path = illustration_file_path(work_id, illustration_id)
    generate_and_save(
        get_api_key(),
        full_prompt,
        save_path,
        settings.chapter_illustration_size,
    )

    markdown_line = build_illustration_markdown(illustration_id)
    new_content = insert_illustration_into_content(
        node.content,
        insert_after_paragraph,
        markdown_line,
    )

    row = ChapterIllustration(
        id=illustration_id,
        work_id=work_id,
        node_id=chapter_node_id,
        file_path=str(save_path),
        prompt=prompt.strip(),
        insert_after_paragraph=insert_after_paragraph,
    )
    db.add(row)
    node.content = new_content
    from services.chapter_history_service import clear_chapter_summary_on_content_change
    clear_chapter_summary_on_content_change(db, node)
    db.commit()
    db.refresh(row)
    db.refresh(node)
    return row
