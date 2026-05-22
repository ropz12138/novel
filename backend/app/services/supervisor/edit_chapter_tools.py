"""EditChapterAgent 工具集"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"


class ReadChapterInput(BaseModel):
    work_id: str
    chapter_number: int


class QueryCharactersByChapterInput(BaseModel):
    work_id: str
    chapter_number: int


class GrepInChapterInput(BaseModel):
    work_id: str
    keyword: str
    chapter_number: int
    context_chars: int = 200


class QueryChapterMetaInput(BaseModel):
    work_id: str
    chapter_number: int


class GrepChapterMetaInput(BaseModel):
    work_id: str
    chapter_number: int
    keyword: str


class RewriteChapterInput(BaseModel):
    work_id: str
    chapter_number: int
    current_content: str
    edit_instruction: str
    story_info: str = ""
    chapter_outline: str = ""


class GeneratePatchEditInput(BaseModel):
    work_id: str
    chapter_number: int
    current_content: str
    edit_instruction: str
    story_info: str = ""
    chapter_outline: str = ""


class SyncChapterMetadataInput(BaseModel):
    work_id: str
    chapter_number: int


def _get_db(config: RunnableConfig) -> Session:
    db = config.get("configurable", {}).get("db")
    if db is None:
        raise ValueError("db Session 未在 configurable 中提供")
    return db


def _get_emit(config: RunnableConfig):
    return config.get("configurable", {}).get("emit", lambda event, data: None)


def _get_db_lock(config: RunnableConfig):
    return config.get("configurable", {}).get("db_lock")


def _with_lock(config: RunnableConfig):
    lock = _get_db_lock(config)
    if lock is not None:
        return lock
    from contextlib import nullcontext
    return nullcontext()


def _get_llm(temperature: float = 0.7):
    from app.services.supervisor.sub_agent_base import get_llm
    return get_llm(temperature=temperature, streaming=True)


@tool(args_schema=ReadChapterInput)
def read_chapter(work_id: str, chapter_number: int, config: RunnableConfig) -> str:
    """读取指定章节正文与基础信息。"""
    from app.models.work_model import Chapter

    db = _get_db(config)
    chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
    if not chapter:
        return f"第{chapter_number}章不存在。"
    if not chapter.content:
        return f"第{chapter_number}章「{chapter.title}」暂无正文内容。"
    return (
        f"第{chapter.chapter_number}章「{chapter.title}」（状态：{chapter.status}）\n"
        f"字数：{len(chapter.content)}\n\n"
        f"--- 正文开始 ---\n{chapter.content}\n--- 正文结束 ---"
    )


@tool(args_schema=QueryCharactersByChapterInput)
def query_characters_by_chapter(work_id: str, chapter_number: int, config: RunnableConfig) -> str:
    """查询本章及之前章节的角色信息。"""
    from app.models.work_model import Character

    db = _get_db(config)
    characters = db.query(Character).filter_by(work_id=work_id).all()
    if not characters:
        return "该作品暂无角色设定。"

    relevant = [c for c in characters if c.first_chapter is None or c.first_chapter <= chapter_number]
    if not relevant:
        return f"第{chapter_number}章暂无出场角色。"

    parts = []
    for c in relevant:
        fields = [f"【{c.name}】{c.role_type}"]
        if c.current_status:
            fields.append(f"状态：{c.current_status}")
        if c.current_goal:
            fields.append(f"目标：{c.current_goal}")
        parts.append("，".join(fields))
    return "\n".join(parts)


@tool(args_schema=GrepInChapterInput)
def grep_in_chapter(work_id: str, keyword: str, chapter_number: int, context_chars: int, config: RunnableConfig) -> str:
    """在章节正文中按关键词检索并返回上下文。"""
    from app.models.work_model import Chapter

    db = _get_db(config)
    chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
    if not chapter or not chapter.content:
        return f"第{chapter_number}章不存在或无正文。"

    content = chapter.content
    results = []
    start = 0
    while True:
        idx = content.find(keyword, start)
        if idx == -1:
            break
        ctx_start = max(0, idx - context_chars)
        ctx_end = min(len(content), idx + len(keyword) + context_chars)
        snippet = content[ctx_start:ctx_end]
        if ctx_start > 0:
            snippet = "..." + snippet
        if ctx_end < len(content):
            snippet = snippet + "..."
        results.append(f"位置 {idx}：{snippet}")
        start = idx + len(keyword)

    if not results:
        return f"在第{chapter_number}章中未找到「{keyword}」。"
    return f"在第{chapter_number}章「{chapter.title}」中找到 {len(results)} 处「{keyword}」：\n" + "\n\n".join(results)


@tool(args_schema=QueryChapterMetaInput)
def query_chapter_meta(work_id: str, chapter_number: int, config: RunnableConfig) -> str:
    """查询章节元数据概览。"""
    from app.models.work_model import ChapterMetadata

    db = _get_db(config)
    row = db.query(ChapterMetadata).filter_by(work_id=work_id, chapter_number=chapter_number).first()
    if not row:
        return f"第{chapter_number}章暂无元数据记录。"

    lines = [
        f"第{chapter_number}章元数据",
        f"摘要：{row.summary or '（无）'}",
        f"关键情节：{len(row.key_plot_points or [])} 条",
        f"大纲关联：{len(row.outline_links or [])} 条",
        f"出场角色：{len(row.involved_characters or [])} 条",
        f"伏笔：{len(row.foreshadows or [])} 条",
        f"事实：{len(row.facts or [])} 条",
    ]
    return "\n".join(lines)


@tool(args_schema=GrepChapterMetaInput)
def grep_chapter_meta(work_id: str, chapter_number: int, keyword: str, config: RunnableConfig) -> str:
    """在章节元数据中检索关键词。"""
    from app.models.work_model import ChapterMetadata

    db = _get_db(config)
    row = db.query(ChapterMetadata).filter_by(work_id=work_id, chapter_number=chapter_number).first()
    if not row:
        return f"第{chapter_number}章暂无元数据记录。"

    haystack = [
        row.summary or "",
        json.dumps(row.key_plot_points or [], ensure_ascii=False),
        json.dumps(row.outline_links or [], ensure_ascii=False),
        json.dumps(row.involved_characters or [], ensure_ascii=False),
        json.dumps(row.foreshadows or [], ensure_ascii=False),
        json.dumps(row.facts or [], ensure_ascii=False),
    ]
    matches = [s for s in haystack if keyword in s]
    if not matches:
        return f"在第{chapter_number}章的元数据中未找到「{keyword}」。"
    return f"在第{chapter_number}章元数据中找到 {len(matches)} 处「{keyword}」。"


def _snapshot_metadata(row) -> dict:
    """将 ChapterMetadata 行快照为可序列化的 dict。"""
    return {
        "summary": row.summary or "",
        "key_plot_points": list(row.key_plot_points or []),
        "outline_links": [dict(item) for item in (row.outline_links or [])],
        "involved_characters": [dict(item) for item in (row.involved_characters or [])],
        "foreshadows": [dict(item) for item in (row.foreshadows or [])],
        "facts": [dict(item) for item in (row.facts or [])],
    }


def _diff_string_list(old_items: list[str], new_items: list[str], field_name: str = "value") -> list[dict]:
    """对比两个字符串列表，返回 added/removed 列表。"""
    old_set = set(old_items)
    new_set = set(new_items)
    result = []
    for item in new_items:
        if item not in old_set:
            result.append({"type": "added", field_name: item})
    for item in old_items:
        if item not in new_set:
            result.append({"type": "removed", field_name: item})
    return result


def _diff_dict_list(old_items: list[dict], new_items: list[dict], key_field: str) -> list[dict]:
    """对比两个 dict 列表，按 key_field 匹配，返回 added/removed/modified 列表。"""
    old_map = {item[key_field]: item for item in old_items if key_field in item}
    new_map = {item[key_field]: item for item in new_items if key_field in item}
    result = []

    for key, new_val in new_map.items():
        if key not in old_map:
            result.append({"type": "added", "data": new_val})
        else:
            old_val = old_map[key]
            changes = _diff_dict_fields(old_val, new_val)
            if changes:
                result.append({"type": "modified", key_field: key, "changes": changes})

    for key in old_map:
        if key not in new_map:
            result.append({"type": "removed", "data": old_map[key]})

    return result


def _diff_dict_fields(old_dict: dict, new_dict: dict) -> list[dict]:
    """对比两个 dict 的字段差异。"""
    all_keys = set(old_dict.keys()) | set(new_dict.keys())
    changes = []
    for k in all_keys:
        old_v = old_dict.get(k)
        new_v = new_dict.get(k)
        old_str = json.dumps(old_v, ensure_ascii=False) if isinstance(old_v, (dict, list)) else str(old_v or "")
        new_str = json.dumps(new_v, ensure_ascii=False) if isinstance(new_v, (dict, list)) else str(new_v or "")
        if old_str != new_str:
            if old_v is None:
                changes.append({"field": k, "type": "added", "new": new_v})
            elif new_v is None:
                changes.append({"field": k, "type": "removed", "old": old_v})
            else:
                changes.append({"field": k, "type": "modified", "old": old_v, "new": new_v})
    return changes


def _build_metadata_diff(old_meta: dict | None, new_meta: dict) -> dict:
    """对比新旧元数据快照，生成结构化 diff。

    返回 {"diff": {...}, "summary": {"total_added": N, "total_modified": N, "total_removed": N}}
    """
    total_added = 0
    total_modified = 0
    total_removed = 0
    diff: dict = {}

    # summary 字段
    old_summary = old_meta.get("summary", "") if old_meta else ""
    new_summary = new_meta.get("summary", "")
    if old_summary != new_summary:
        if old_meta is None:
            diff["summary"] = {"type": "added", "new": new_summary}
            total_added += 1
        else:
            diff["summary"] = {"type": "modified", "old": old_summary, "new": new_summary}
            total_modified += 1

    # key_plot_points：字符串列表
    old_kpp = old_meta.get("key_plot_points", []) if old_meta else []
    new_kpp = new_meta.get("key_plot_points", [])
    kpp_diff = _diff_string_list(old_kpp, new_kpp, "value")
    if kpp_diff:
        diff["key_plot_points"] = kpp_diff
        total_added += sum(1 for d in kpp_diff if d["type"] == "added")
        total_removed += sum(1 for d in kpp_diff if d["type"] == "removed")

    # involved_characters：dict 列表，按 name 匹配
    old_ic = old_meta.get("involved_characters", []) if old_meta else []
    new_ic = new_meta.get("involved_characters", [])
    ic_diff = _diff_dict_list(old_ic, new_ic, "name")
    if ic_diff:
        diff["involved_characters"] = ic_diff
        total_added += sum(1 for d in ic_diff if d["type"] == "added")
        total_removed += sum(1 for d in ic_diff if d["type"] == "removed")
        total_modified += sum(1 for d in ic_diff if d["type"] == "modified")

    # foreshadows：dict 列表，按 content 匹配
    old_fs = old_meta.get("foreshadows", []) if old_meta else []
    new_fs = new_meta.get("foreshadows", [])
    fs_diff = _diff_dict_list(old_fs, new_fs, "content")
    if fs_diff:
        diff["foreshadows"] = fs_diff
        total_added += sum(1 for d in fs_diff if d["type"] == "added")
        total_removed += sum(1 for d in fs_diff if d["type"] == "removed")
        total_modified += sum(1 for d in fs_diff if d["type"] == "modified")

    # facts：dict 列表，按 key 匹配
    old_ft = old_meta.get("facts", []) if old_meta else []
    new_ft = new_meta.get("facts", [])
    ft_diff = _diff_dict_list(old_ft, new_ft, "key")
    if ft_diff:
        diff["facts"] = ft_diff
        total_added += sum(1 for d in ft_diff if d["type"] == "added")
        total_removed += sum(1 for d in ft_diff if d["type"] == "removed")
        total_modified += sum(1 for d in ft_diff if d["type"] == "modified")

    # outline_links：dict 列表，按 id 匹配
    old_ol = old_meta.get("outline_links", []) if old_meta else []
    new_ol = new_meta.get("outline_links", [])
    ol_diff = _diff_dict_list(old_ol, new_ol, "id")
    if ol_diff:
        diff["outline_links"] = ol_diff
        total_added += sum(1 for d in ol_diff if d["type"] == "added")
        total_removed += sum(1 for d in ol_diff if d["type"] == "removed")
        total_modified += sum(1 for d in ol_diff if d["type"] == "modified")

    return {
        "diff": diff,
        "summary": {
            "total_added": total_added,
            "total_modified": total_modified,
            "total_removed": total_removed,
            "total_changes": total_added + total_modified + total_removed,
        },
    }


async def _save_content_only(*, work_id: str, chapter_number: int, new_content: str, config: RunnableConfig) -> str:
    """保存正文到 DB，不触发元数据生成。"""
    from app.models.work_model import Chapter, Work

    db = _get_db(config)
    emit = _get_emit(config)

    try:
        with _with_lock(config):
            chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
            if not chapter:
                return f"第{chapter_number}章不存在，无法保存。"
            chapter.content = new_content
            chapter.status = "已保存"
            work = db.query(Work).filter_by(id=work_id).first()
            if not work:
                db.rollback()
                return f"作品 {work_id} 不存在。"
            db.commit()
    except Exception as exc:
        with _with_lock(config):
            db.rollback()
        return f"第{chapter_number}章保存失败：{exc!r}"

    word_count = len(new_content.replace("\n", "").replace(" ", ""))
    emit("edit_chapter_applied", {"chapter_number": chapter_number, "title": chapter.title, "word_count": word_count})

    return (
        f"第{chapter_number}章「{chapter.title}」正文已保存。"
        f"字数：{word_count}。"
    )


async def _sync_chapter_metadata_coroutine(
    work_id: str,
    chapter_number: int,
    config: RunnableConfig = None,
) -> str:
    """独立元数据同步工具：根据当前章节正文重新生成结构化元数据。"""
    from app.models.work_model import Chapter, ChapterMetadata, Work
    from app.services.chapter_outline_sync_service import ChapterOutlineSyncService

    db = _get_db(config)
    emit = _get_emit(config)

    chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
    if not chapter or not chapter.content:
        return f"第{chapter_number}章不存在或无正文，无法同步元数据。"

    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    old_meta_row = db.query(ChapterMetadata).filter_by(work_id=work_id, chapter_number=chapter_number).first()
    old_meta = _snapshot_metadata(old_meta_row) if old_meta_row else None

    emit("stage_start", {"stage": "sync_metadata", "label": f"同步第{chapter_number}章元数据"})

    try:
        with _with_lock(config):
            metadata_row = await ChapterOutlineSyncService.generate_and_persist(db, work=work, chapter=chapter)
            db.commit()
    except Exception as exc:
        with _with_lock(config):
            db.rollback()
        return f"第{chapter_number}章元数据同步失败：{exc!r}"

    new_meta = _snapshot_metadata(metadata_row)
    diff_result = _build_metadata_diff(old_meta, new_meta)

    emit("chapter_metadata_diff", {
        "chapter_number": chapter_number,
        "summary": metadata_row.summary,
        "key_plot_points": metadata_row.key_plot_points,
        "outline_links": metadata_row.outline_links,
        "involved_characters": metadata_row.involved_characters,
        "foreshadows": metadata_row.foreshadows,
        "facts": metadata_row.facts,
        "updated_at": metadata_row.updated_at.isoformat() if metadata_row.updated_at else None,
        "diff": diff_result["diff"],
        "diff_summary": diff_result["summary"],
    })

    return (
        f"第{chapter_number}章元数据已同步。"
        f"摘要：{(metadata_row.summary or '')[:100]}；"
        f"关键情节 {len(metadata_row.key_plot_points or [])} 条；"
        f"变更 {diff_result['summary']['total_changes']} 处。"
    )


async def _rewrite_chapter_coroutine(
    work_id: str,
    chapter_number: int,
    current_content: str,
    edit_instruction: str,
    story_info: str = "",
    chapter_outline: str = "",
    config: RunnableConfig = None,
) -> str:
    emit = _get_emit(config)

    template = (PROMPT_DIR / "edit_chapter.txt").read_text(encoding="utf-8")
    prompt = PromptTemplate.from_template(template)
    llm = _get_llm(temperature=0.7)
    chain = prompt | llm

    new_content = ""
    async for chunk in chain.astream({
        "story_info": story_info or "（未提供）",
        "chapter_outline": chapter_outline or "（未提供）",
        "current_content": current_content,
        "user_message": edit_instruction,
    }):
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        new_content += text
        emit("edit_chapter_stream", {"chunk": text})

    final_content = new_content.strip()
    result = await _save_content_only(
        work_id=work_id,
        chapter_number=chapter_number,
        new_content=final_content,
        config=config,
    )
    return f"{result}\n\n--- 修改后正文 ---\n{final_content}"


def _parse_patch_json(raw: str) -> list[dict]:
    text = raw.strip()
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1).strip()

    data = json.loads(text)

    if not isinstance(data, dict) or "edits" not in data:
        raise ValueError("局部编辑输出必须是包含 edits 字段的 JSON 对象")

    edit_ops = []
    for e in data.get("edits", []):
        if not isinstance(e, dict):
            raise ValueError("edits 中的每个元素都必须是对象")
        if e.get("type") not in ("replace", "insert", "delete"):
            raise ValueError("edit.type 只能是 replace、insert 或 delete")
        edit_ops.append(
            {
                "type": e.get("type"),
                "search": e.get("search", ""),
                "after": e.get("after", ""),
                "content": e.get("content", ""),
            }
        )
    if not edit_ops:
        raise ValueError("局部编辑输出 edits 为空")
    return edit_ops


async def _generate_patch_edit_coroutine(
    work_id: str,
    chapter_number: int,
    current_content: str,
    edit_instruction: str,
    story_info: str = "",
    chapter_outline: str = "",
    config: RunnableConfig = None,
) -> str:
    from app.services.supervisor.edit_patch import EditOperation, apply_edits

    emit = _get_emit(config)
    template = (PROMPT_DIR / "edit_chapter_patch.txt").read_text(encoding="utf-8")
    prompt = PromptTemplate.from_template(template)
    llm = _get_llm(temperature=0.7)
    chain = prompt | llm

    raw_output = ""
    async for chunk in chain.astream({
        "story_info": story_info or "（未提供）",
        "chapter_outline": chapter_outline or "（未提供）",
        "current_content": current_content,
        "user_message": edit_instruction,
    }):
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        raw_output += text
        emit("edit_chapter_stream", {"chunk": text})

    edit_ops = _parse_patch_json(raw_output)
    ops = [
        EditOperation(
            type=op["type"],
            search=op.get("search", ""),
            after=op.get("after", ""),
            content=op.get("content", ""),
        )
        for op in edit_ops
    ]
    result = apply_edits(current_content, ops)
    if not result.success:
        raise ValueError(result.message)
    new_content = result.content

    save_result = await _save_content_only(
        work_id=work_id,
        chapter_number=chapter_number,
        new_content=new_content,
        config=config,
    )
    return f"{save_result}\n\n--- 修改后正文 ---\n{new_content}"


rewrite_chapter = StructuredTool.from_function(
    func=None,
    coroutine=_rewrite_chapter_coroutine,
    name="rewrite_chapter",
    description=(
        "重写工具：根据编辑指令生成完整改写后的章节正文，并自动保存。"
        "在使用前先调用 read_chapter 获取当前正文。"
        "正文保存后，应紧接着调用 sync_chapter_metadata 同步元数据。"
    ),
    args_schema=RewriteChapterInput,
)


generate_patch_edit = StructuredTool.from_function(
    func=None,
    coroutine=_generate_patch_edit_coroutine,
    name="generate_patch_edit",
    description=(
        "根据编辑指令执行局部补丁编辑，并自动保存正文。"
        "正文保存后，应紧接着调用 sync_chapter_metadata 同步元数据。"
    ),
    args_schema=GeneratePatchEditInput,
)


sync_chapter_metadata = StructuredTool.from_function(
    func=None,
    coroutine=_sync_chapter_metadata_coroutine,
    name="sync_chapter_metadata",
    description=(
        "同步章节元数据：根据当前章节正文重新生成结构化元数据（摘要、关键情节、伏笔、事实等）。"
        "在正文保存后调用以更新元数据。每次正文修改后都应调用此工具。"
    ),
    args_schema=SyncChapterMetadataInput,
)


EDIT_CHAPTER_TOOLS = [
    read_chapter,
    query_characters_by_chapter,
    grep_in_chapter,
    query_chapter_meta,
    grep_chapter_meta,
    generate_patch_edit,
    rewrite_chapter,
    sync_chapter_metadata,
]
