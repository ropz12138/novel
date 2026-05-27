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
    chapter_start: int = 1
    chapter_end: int | None = None
    chapter_number: int | None = None


class QueryCharactersByChapterInput(BaseModel):
    chapter_start: int = 1
    chapter_end: int | None = None
    chapter_number: int | None = None


class GrepInChapterInput(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    chapter_start: int = 1
    chapter_end: int | None = None
    chapter_number: int | None = None
    keyword: str | None = None
    context_chars: int = 200


class QueryChapterMetaInput(BaseModel):
    chapter_start: int = 1
    chapter_end: int | None = None
    chapter_number: int | None = None


class GrepChapterMetaInput(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    chapter_start: int = 1
    chapter_end: int | None = None
    chapter_number: int | None = None
    keyword: str | None = None


class RewriteChapterInput(BaseModel):
    chapter_number: int
    current_content: str
    edit_instruction: str
    story_info: str = ""
    chapter_outline: str = ""


class GeneratePatchEditInput(BaseModel):
    chapter_number: int
    current_content: str
    edit_instruction: str
    story_info: str = ""
    chapter_outline: str = ""


class SyncChapterMetadataInput(BaseModel):
    chapter_number: int


class OverwriteChapterTitleInput(BaseModel):
    chapter_number: int
    new_title: str = Field(description="新的章节标题（全量覆盖）")


def _get_db(config: RunnableConfig) -> Session:
    db = config.get("configurable", {}).get("db")
    if db is None:
        raise ValueError("db Session 未在 configurable 中提供")
    return db


def _get_emit(config: RunnableConfig):
    return config.get("configurable", {}).get("emit", lambda event, data: None)


def _get_work_id(config: RunnableConfig) -> str:
    work_id = str(config.get("configurable", {}).get("work_id") or "")
    if work_id:
        return work_id
    configurable = config.get("configurable", {})
    session_id = configurable.get("supervisor_session_id")
    if session_id:
        db = configurable.get("db")
        if db:
            from app.models.agent_model import SupervisorSession
            session = db.query(SupervisorSession).filter_by(id=session_id).first()
            if session and session.work_id:
                return str(session.work_id)
    raise ValueError("work_id 未在 configurable 中提供")


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
def read_chapter(
    chapter_start: int = 1,
    chapter_end: int | None = None,
    chapter_number: int | None = None,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """读取章节范围正文与基础信息。"""
    from app.models.work_model import Chapter

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
    if chapter_number is not None:
        chapter_start = chapter_number
        chapter_end = chapter_number
    if chapter_end is None:
        chapter_end = chapter_start
    if chapter_start > chapter_end:
        chapter_start, chapter_end = chapter_end, chapter_start

    rows = (
        db.query(Chapter)
        .filter_by(work_id=work_id)
        .filter(Chapter.chapter_number >= chapter_start)
        .filter(Chapter.chapter_number <= chapter_end)
        .order_by(Chapter.chapter_number.asc())
        .all()
    )
    if not rows:
        return f"第{chapter_start}~{chapter_end}章不存在。"

    parts = []
    for chapter in rows:
        if not chapter.content:
            parts.append(f"第{chapter.chapter_number}章「{chapter.title}」暂无正文内容。")
            continue
        parts.append(
            f"第{chapter.chapter_number}章「{chapter.title}」（状态：{chapter.status}）\n"
            f"字数：{len(chapter.content)}\n\n"
            f"--- 正文开始 ---\n{chapter.content}\n--- 正文结束 ---"
        )
    return "\n\n".join(parts)


@tool(args_schema=QueryCharactersByChapterInput)
def query_characters_by_chapter(
    chapter_start: int = 1,
    chapter_end: int | None = None,
    chapter_number: int | None = None,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """查询章节范围对应上下文的角色信息。"""
    from app.models.work_model import Character

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
    if chapter_number is not None:
        chapter_start = chapter_number
        chapter_end = chapter_number
    if chapter_end is None:
        chapter_end = chapter_start
    target_chapter = max(chapter_start, chapter_end)

    characters = db.query(Character).filter_by(work_id=work_id).all()
    if not characters:
        return "该作品暂无角色设定。"

    relevant = [c for c in characters if c.first_chapter is None or c.first_chapter <= target_chapter]
    if not relevant:
        return f"第{chapter_start}~{chapter_end}章暂无出场角色。"

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
def grep_in_chapter(
    keywords: list[str],
    chapter_start: int = 1,
    context_chars: int = 200,
    chapter_end: int | None = None,
    chapter_number: int | None = None,
    keyword: str | None = None,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """在章节范围正文中按多个关键词检索并返回上下文。"""
    from app.models.work_model import Chapter

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
    if chapter_number is not None:
        chapter_start = chapter_number
        chapter_end = chapter_number
    if chapter_end is None:
        chapter_end = chapter_start
    if chapter_start > chapter_end:
        chapter_start, chapter_end = chapter_end, chapter_start

    kw_list = [k for k in (keywords or []) if k]
    if keyword:
        kw_list.append(keyword)
    kw_list = list(dict.fromkeys(kw_list))
    if not kw_list:
        return "检索失败：请至少提供一个关键词。"

    chapters = (
        db.query(Chapter)
        .filter_by(work_id=work_id)
        .filter(Chapter.chapter_number >= chapter_start)
        .filter(Chapter.chapter_number <= chapter_end)
        .order_by(Chapter.chapter_number.asc())
        .all()
    )
    if not chapters:
        return f"第{chapter_start}~{chapter_end}章不存在。"

    output = []
    for kw in kw_list:
        kw_hits = []
        for chapter in chapters:
            content = chapter.content or ""
            if not content:
                continue
            start = 0
            while True:
                idx = content.find(kw, start)
                if idx == -1:
                    break
                ctx_start = max(0, idx - context_chars)
                ctx_end = min(len(content), idx + len(kw) + context_chars)
                snippet = content[ctx_start:ctx_end]
                if ctx_start > 0:
                    snippet = "..." + snippet
                if ctx_end < len(content):
                    snippet = snippet + "..."
                kw_hits.append(
                    f"第{chapter.chapter_number}章「{chapter.title}」位置 {idx}：{snippet}"
                )
                start = idx + len(kw)
        if kw_hits:
            output.append(f"关键词「{kw}」命中 {len(kw_hits)} 处：\n" + "\n\n".join(kw_hits))
        else:
            output.append(f"关键词「{kw}」在第{chapter_start}~{chapter_end}章未命中。")

    return "\n\n".join(output)


@tool(args_schema=QueryChapterMetaInput)
def query_chapter_meta(
    chapter_start: int = 1,
    chapter_end: int | None = None,
    chapter_number: int | None = None,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """查询章节范围元数据概览。"""
    from app.models.work_model import ChapterMetadata

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
    if chapter_number is not None:
        chapter_start = chapter_number
        chapter_end = chapter_number
    if chapter_end is None:
        chapter_end = chapter_start
    if chapter_start > chapter_end:
        chapter_start, chapter_end = chapter_end, chapter_start

    rows = (
        db.query(ChapterMetadata)
        .filter_by(work_id=work_id)
        .filter(ChapterMetadata.chapter_number >= chapter_start)
        .filter(ChapterMetadata.chapter_number <= chapter_end)
        .order_by(ChapterMetadata.chapter_number.asc())
        .all()
    )
    if not rows:
        return f"第{chapter_start}~{chapter_end}章暂无元数据记录。"

    blocks = []
    for row in rows:
        blocks.append("\n".join([
            f"第{row.chapter_number}章元数据",
            f"摘要：{row.summary or '（无）'}",
            f"关键情节：{len(row.key_plot_points or [])} 条",
            f"大纲关联：{len(row.outline_links or [])} 条",
            f"出场角色：{len(row.involved_characters or [])} 条",
            f"伏笔：{len(row.foreshadows or [])} 条",
            f"事实：{len(row.facts or [])} 条",
        ]))
    return "\n\n".join(blocks)


@tool(args_schema=GrepChapterMetaInput)
def grep_chapter_meta(
    keywords: list[str],
    chapter_start: int = 1,
    chapter_end: int | None = None,
    chapter_number: int | None = None,
    keyword: str | None = None,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """在章节范围元数据中按多个关键词检索。"""
    from app.models.work_model import ChapterMetadata

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
    if chapter_number is not None:
        chapter_start = chapter_number
        chapter_end = chapter_number
    if chapter_end is None:
        chapter_end = chapter_start
    if chapter_start > chapter_end:
        chapter_start, chapter_end = chapter_end, chapter_start

    kw_list = [k for k in (keywords or []) if k]
    if keyword:
        kw_list.append(keyword)
    kw_list = list(dict.fromkeys(kw_list))
    if not kw_list:
        return "检索失败：请至少提供一个关键词。"

    rows = (
        db.query(ChapterMetadata)
        .filter_by(work_id=work_id)
        .filter(ChapterMetadata.chapter_number >= chapter_start)
        .filter(ChapterMetadata.chapter_number <= chapter_end)
        .order_by(ChapterMetadata.chapter_number.asc())
        .all()
    )
    if not rows:
        return f"第{chapter_start}~{chapter_end}章暂无元数据记录。"

    lines = []
    for kw in kw_list:
        hit_count = 0
        hit_chapters = []
        for row in rows:
            haystack = [
                row.summary or "",
                json.dumps(row.key_plot_points or [], ensure_ascii=False),
                json.dumps(row.outline_links or [], ensure_ascii=False),
                json.dumps(row.involved_characters or [], ensure_ascii=False),
                json.dumps(row.foreshadows or [], ensure_ascii=False),
                json.dumps(row.facts or [], ensure_ascii=False),
            ]
            matches = [s for s in haystack if kw in s]
            if matches:
                hit_count += len(matches)
                hit_chapters.append(str(row.chapter_number))
        if hit_count:
            lines.append(f"关键词「{kw}」在章节 {', '.join(hit_chapters)} 共命中 {hit_count} 处。")
        else:
            lines.append(f"关键词「{kw}」在第{chapter_start}~{chapter_end}章未命中。")

    return "\n".join(lines)


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
    chapter_number: int,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """独立元数据同步工具：根据当前章节正文重新生成结构化元数据。"""
    from app.models.work_model import Chapter, ChapterMetadata, Work
    from app.services.chapter_outline_sync_service import ChapterOutlineSyncService

    db = _get_db(config)
    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)

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
    chapter_number: int,
    current_content: str,
    edit_instruction: str,
    story_info: str = "",
    chapter_outline: str = "",
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)

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
    chapter_number: int,
    current_content: str,
    edit_instruction: str,
    story_info: str = "",
    chapter_outline: str = "",
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    from app.services.supervisor.edit_patch import EditOperation, apply_edits

    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)
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


async def _overwrite_chapter_title_coroutine(
    chapter_number: int,
    new_title: str,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """全量覆盖章节标题，不修改正文。"""
    from app.models.work_model import Chapter

    db = _get_db(config)
    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)

    normalized = (new_title or "").strip()
    if not normalized:
        return "标题覆盖失败：new_title 不能为空。"
    if len(normalized) > 200:
        return "标题覆盖失败：new_title 不能超过 200 个字符。"

    try:
        with _with_lock(config):
            chapter = db.query(Chapter).filter_by(
                work_id=work_id, chapter_number=chapter_number
            ).first()
            if not chapter:
                return f"第{chapter_number}章不存在，无法覆盖标题。"

            old_title = chapter.title or ""
            chapter.title = normalized
            db.commit()
            db.refresh(chapter)
    except Exception as exc:
        with _with_lock(config):
            db.rollback()
        return f"第{chapter_number}章标题覆盖失败：{exc!r}"

    emit(
        "chapter_title_overwritten",
        {
            "chapter_number": chapter_number,
            "old_title": old_title,
            "new_title": chapter.title,
        },
    )
    return f"第{chapter_number}章标题已覆盖：{old_title or '（空）'} -> {chapter.title}"


overwrite_chapter_title = StructuredTool.from_function(
    func=None,
    coroutine=_overwrite_chapter_title_coroutine,
    name="overwrite_chapter_title",
    description=(
        "全量覆盖章节标题（不修改正文）。"
        "当用户明确要求改标题、重命名章节时使用此工具。"
    ),
    args_schema=OverwriteChapterTitleInput,
)


from app.services.supervisor.outline_tools import (  # noqa: E402
    create_child_todolist,
    read_child_todolist,
    update_child_task_status,
)

EDIT_CHAPTER_TOOLS = [
    create_child_todolist,
    read_child_todolist,
    update_child_task_status,
    read_chapter,
    query_characters_by_chapter,
    grep_in_chapter,
    query_chapter_meta,
    grep_chapter_meta,
    generate_patch_edit,
    rewrite_chapter,
    overwrite_chapter_title,
    sync_chapter_metadata,
]
