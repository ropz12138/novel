"""EvaluationAgent 工具集

章节评估子 Agent 可调用的工具，封装章节读取、上下文查询和双视角评估。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"


# ── Tool input schemas ──


class ReadChapterForEvalInput(BaseModel):
    chapter_start: int = Field(default=1, description="起始章节号")
    chapter_end: int | None = Field(default=None, description="结束章节号")
    chapter_number: int | None = Field(default=None, description="兼容字段：单章节号")


class ReadChapterOutlineForEvalInput(BaseModel):
    chapter_start: int = Field(default=1, description="起始章节号")
    chapter_end: int | None = Field(default=None, description="结束章节号")
    chapter_number: int | None = Field(default=None, description="兼容字段：单章节号")


class ReadPreviousChaptersForEvalInput(BaseModel):
    chapter_start: int = Field(default=1, description="起始章节号")
    chapter_end: int | None = Field(default=None, description="结束章节号")
    chapter_number: int | None = Field(default=None, description="兼容字段：单章节号")
    limit: int = Field(default=3, description="每个目标章节向前读取几章")


class EvaluateAsEditorInput(BaseModel):
    chapter_content: str = Field(description="要评估的章节正文")
    story_info: str = Field(default="", description="作品信息")
    chapter_outline: str = Field(default="", description="本章大纲")
    previous_chapters: str = Field(default="", description="前文回顾")


class EvaluateAsReaderInput(BaseModel):
    chapter_content: str = Field(description="要评估的章节正文")
    story_info: str = Field(default="", description="作品信息")
    chapter_outline: str = Field(default="", description="本章大纲")
    previous_chapters: str = Field(default="", description="前文回顾")


class EvaluateChapterOutlineSyncInput(BaseModel):
    chapter_number: int = Field(description="要评估的章节号")
    trigger: str = Field(default="run", description="触发参数，保持默认即可")


class EvaluateChapterAllInput(BaseModel):
    chapter_number: int = Field(description="要评估的章节号")
    evaluations: list[str] = Field(
        default=["editor", "reader", "sync"],
        description="要并行执行的评估类型列表，可选值：editor（编辑视角）、reader（读者视角）、sync（大纲同步性）。默认全部执行。",
    )


# ── Helpers ──


def _get_db(config: RunnableConfig) -> Session:
    configurable = config.get("configurable", {})
    db = configurable.get("db")
    if db is None:
        raise ValueError("db Session 未在 configurable 中提供")
    return db


def _get_emit(config: RunnableConfig):
    configurable = config.get("configurable", {})
    return configurable.get("emit", lambda event, data: None)


def _get_work_chapter_from_config(config: RunnableConfig) -> tuple[str, int]:
    configurable = config.get("configurable", {})
    work_id = str(configurable.get("work_id", "") or "")
    chapter_number = int(configurable.get("chapter_number", 0) or 0)
    if not work_id or chapter_number <= 0:
        raise ValueError("缺少 work_id/chapter_number 上下文")
    return work_id, chapter_number


def _get_work_id(config: RunnableConfig) -> str:
    work_id = str(config.get("configurable", {}).get("work_id", "") or "")
    if work_id is not None and work_id != "":
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


# ── 工具实现 ──


@tool(args_schema=ReadChapterForEvalInput)
def read_chapter_for_eval(
    chapter_start: int = 1,
    chapter_end: int | None = None,
    chapter_number: int | None = None,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """读取要评估的章节正文。评估前必须先调用此工具。"""
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

    parts = []
    for chapter in chapters:
        if not chapter.content:
            parts.append(f"第{chapter.chapter_number}章「{chapter.title}」暂无正文内容。")
        else:
            parts.append(f"第{chapter.chapter_number}章「{chapter.title}」\n\n{chapter.content}")
    return "\n\n".join(parts)


@tool(args_schema=ReadChapterOutlineForEvalInput)
def read_chapter_outline_for_eval(
    chapter_start: int = 1,
    chapter_end: int | None = None,
    chapter_number: int | None = None,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """读取本章的大纲节点信息，用于评估正文是否偏离大纲。"""
    from app.models.work_model import Work
    from app.services.work_service import WorkService

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    if chapter_number is not None:
        chapter_start = chapter_number
        chapter_end = chapter_number
    if chapter_end is None:
        chapter_end = chapter_start
    if chapter_start > chapter_end:
        chapter_start, chapter_end = chapter_end, chapter_start

    parts = []
    for ch_no in range(chapter_start, chapter_end + 1):
        chapter_outline = WorkService._find_chapter_outline(work.outline_tree, ch_no)
        parts.append(chapter_outline or f"第{ch_no}章未找到对应的大纲节点。")
    return "\n\n".join(parts)


@tool(args_schema=ReadPreviousChaptersForEvalInput)
def read_previous_chapters_for_eval(
    chapter_start: int = 1,
    limit: int = 3,
    chapter_end: int | None = None,
    chapter_number: int | None = None,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """读取前几章的正文摘要，用于评估上下文连贯性。"""
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

    blocks = []
    for target_ch in range(chapter_start, chapter_end + 1):
        prev_chapters = (
            db.query(Chapter)
            .filter_by(work_id=work_id)
            .filter(Chapter.chapter_number < target_ch)
            .filter(Chapter.content != "")
            .order_by(Chapter.chapter_number.desc())
            .limit(limit)
            .all()
        )
        prev_chapters.reverse()

        if not prev_chapters:
            blocks.append(f"第{target_ch}章：这是第一章，暂无前文。")
            continue

        parts = [f"第{target_ch}章前文："]
        for ch in prev_chapters:
            parts.append(f"--- 第{ch.chapter_number}章 {ch.title} ---\n{ch.content}")
        blocks.append("\n\n".join(parts))

    return "\n\n".join(blocks)


def _outline_to_natural_text(outline: dict) -> str:
    story = outline.get("story", {}) if isinstance(outline, dict) else {}
    macro_phases = outline.get("outline", {}).get("macro_phases", []) if isinstance(outline, dict) else []
    meso_stages = outline.get("meso", {}).get("meso_stages", []) if isinstance(outline, dict) else []
    foreshadowing = outline.get("foreshadowing", []) if isinstance(outline, dict) else []

    lines: list[str] = []
    lines.append("【作品信息】")
    lines.append(f"标题：{story.get('title', '')}")
    lines.append(f"类型：{story.get('genre', '')}")
    lines.append(f"卷：{story.get('volume', '')}")
    lines.append(f"简介：{story.get('synopsis', '')}")

    lines.append("\n【大纲（宏观阶段）】")
    for p in macro_phases:
        cr = p.get("chapter_range", [0, 0])
        lines.append(
            f"- {p.get('id', '')} | 章节 {cr[0]}-{cr[1]} | "
            f"{p.get('name', '')} | 目标：{p.get('goal', '')}"
        )

    lines.append("\n【中纲（故事阶段）】")
    for s in meso_stages:
        cr = s.get("chapter_range", [0, 0])
        lines.append(
            f"- {s.get('id', '')} | 章节 {cr[0]}-{cr[1]} | "
            f"{s.get('name', '')}（{s.get('type', '')}）| 冲突：{s.get('conflict', '')}"
        )

    lines.append("\n【伏笔】")
    for f in foreshadowing:
        lines.append(
            f"- {f.get('id', '')} | 埋设：{f.get('plant_node', '')} | 回收：{f.get('payoff_node', '')} | "
            f"内容：{f.get('content', '')}"
        )
    return "\n".join(lines)


def _characters_to_natural_text(characters: list[Any]) -> str:
    if not characters:
        return "【角色表】暂无角色。"
    lines = ["【角色表】"]
    for c in characters:
        lines.append(
            f"- {c.name}（{c.role_type}）：性格={c.personality or ''}；背景={c.background or ''}；"
            f"状态={c.current_status or ''}；目标={c.current_goal or ''}；首次出场阶段={c.first_appearance_stage or ''}"
        )
    return "\n".join(lines)


def _metadata_to_natural_text(md: Any) -> str:
    if not md:
        return "【最新章节元数据】暂无。"
    lines = ["【最新章节元数据】"]
    lines.append(f"摘要：{md.summary or ''}")
    lines.append(f"关键情节点：{'; '.join(md.key_plot_points or [])}")
    lines.append(f"大纲关联：{'; '.join(str(x) for x in (md.outline_links or []))}")
    lines.append(f"涉及角色：{'; '.join(str(x) for x in (md.involved_characters or []))}")
    lines.append(f"事实：{'; '.join(str(x) for x in (md.facts or []))}")
    return "\n".join(lines)


def _history_summaries_to_natural_text(rows: list[Any]) -> str:
    if not rows:
        return "【历史章节梗概】无。"
    lines = ["【历史章节梗概（完整，不截断）】"]
    for r in rows:
        lines.append(f"- 第{r.chapter_number}章：{r.summary or ''}")
    return "\n".join(lines)


async def _evaluate_chapter_outline_sync_coroutine(
    chapter_number: int,
    trigger: str = "run",
    config: RunnableConfig = None,
) -> str:
    """评估最新章节与大纲的同步性（工具内部一次 LLM 交互完成）。"""
    from langchain_core.messages import HumanMessage

    from app.models.work_model import Chapter, ChapterMetadata, Character, Work
    from app.services.supervisor.sub_agent_base import get_llm

    del trigger

    db = _get_db(config)
    emit = _get_emit(config)
    work_id = _get_work_id(config)
    if chapter_number <= 0:
        return "同步性评估失败：必须显式传入有效的 chapter_number。"

    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"同步性评估失败：作品 {work_id} 不存在。"

    chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
    if not chapter or not chapter.content:
        return f"同步性评估失败：第{chapter_number}章正文不存在。"

    latest_md = db.query(ChapterMetadata).filter_by(work_id=work_id, chapter_number=chapter_number).first()
    history_md = (
        db.query(ChapterMetadata)
        .filter(ChapterMetadata.work_id == work_id, ChapterMetadata.chapter_number < chapter_number)
        .order_by(ChapterMetadata.chapter_number.asc())
        .all()
    )
    characters = (
        db.query(Character)
        .filter_by(work_id=work_id)
        .order_by(Character.first_appearance_stage.asc(), Character.created_at.asc())
        .all()
    )

    outline_text = _outline_to_natural_text(work.outline_tree or {})
    chars_text = _characters_to_natural_text(characters)
    latest_chapter_text = f"【最新章节正文】\n第{chapter_number}章《{chapter.title or ''}》\n{chapter.content}"
    latest_md_text = _metadata_to_natural_text(latest_md)
    history_text = _history_summaries_to_natural_text(history_md)

    prompt = (
        "你是一名长篇网文总编审，请评估「最新章节」与「大纲」的同步关系。\n"
        "要求：\n"
        "1) 允许「节奏放缓导致事件延后」，但要判断是否有铺垫且因果不断裂。\n"
        "2) 直接输出自然语言评估，不要输出 JSON、代码块或键值对象。\n"
        "3) 请按以下自然语言格式输出：\n"
        "同步性评分：0-100分。\n"
        "状态：aligned / partial_mismatch / major_mismatch 三选一，并用中文解释。\n"
        "建议动作：none / fix_chapter / fix_outline / fix_both 四选一，并解释为什么。\n"
        "主要不同步点：逐条说明大纲要求、正文实际情况、差异类型、严重程度。\n"
        "修复建议：说明应该改正文、改大纲、改元数据，或组合处理。\n"
        "下一章关注：列出下一章必须对齐的检查点。\n\n"
        f"{outline_text}\n\n{chars_text}\n\n{latest_chapter_text}\n\n{latest_md_text}\n\n{history_text}"
    )

    llm = get_llm(temperature=0.1, streaming=False)
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    content = getattr(response, "content", "") or ""
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    content = str(content).strip()

    emit("evaluation_sync_done", {"chapter_number": chapter_number, "raw": content})
    return content


async def _evaluate_as_editor_coroutine(
    chapter_content: str,
    story_info: str = "",
    chapter_outline: str = "",
    previous_chapters: str = "",
    config: RunnableConfig = None,
) -> str:
    """以编辑视角评估章节质量，返回纯文本评估。"""
    from langchain_core.messages import HumanMessage

    from app.services.supervisor.sub_agent_base import get_llm

    emit = _get_emit(config)

    template = (PROMPT_DIR / "agent_evaluate_editor.txt").read_text(encoding="utf-8")
    prompt_text = PromptTemplate.from_template(template).format(
        story_info=story_info,
        chapter_outline=chapter_outline or "（未找到本章大纲）",
        chapter_title="待评估章节",
        chapter_content=chapter_content,
        previous_chapters=previous_chapters,
    )

    llm = get_llm(temperature=0.2, streaming=False)
    response = await llm.ainvoke([HumanMessage(content=prompt_text)])
    content = getattr(response, "content", "") or ""
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    content = str(content).strip()

    emit("evaluation_editor_done", {"chapter_content_preview": content})
    return content


async def _evaluate_as_reader_coroutine(
    chapter_content: str,
    story_info: str = "",
    chapter_outline: str = "",
    previous_chapters: str = "",
    config: RunnableConfig = None,
) -> str:
    """以读者视角评估章节质量，返回纯文本评估。"""
    from langchain_core.messages import HumanMessage

    from app.services.supervisor.sub_agent_base import get_llm

    emit = _get_emit(config)

    template = (PROMPT_DIR / "agent_evaluate_reader.txt").read_text(encoding="utf-8")
    prompt_text = PromptTemplate.from_template(template).format(
        story_info=story_info,
        chapter_outline=chapter_outline or "（未找到本章大纲）",
        chapter_title="待评估章节",
        chapter_content=chapter_content,
        previous_chapters=previous_chapters,
    )

    llm = get_llm(temperature=0.2, streaming=False)
    response = await llm.ainvoke([HumanMessage(content=prompt_text)])
    content = getattr(response, "content", "") or ""
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    content = str(content).strip()

    emit("evaluation_reader_done", {"chapter_content_preview": content})
    return content


evaluate_as_editor = StructuredTool.from_function(
    func=None,
    coroutine=_evaluate_as_editor_coroutine,
    name="evaluate_as_editor",
    description="以编辑视角评估章节质量，返回自然语言评估。",
    args_schema=EvaluateAsEditorInput,
)

evaluate_as_reader = StructuredTool.from_function(
    func=None,
    coroutine=_evaluate_as_reader_coroutine,
    name="evaluate_as_reader",
    description="以读者视角评估章节质量，返回自然语言评估。",
    args_schema=EvaluateAsReaderInput,
)

evaluate_chapter_outline_sync = StructuredTool.from_function(
    func=None,
    coroutine=_evaluate_chapter_outline_sync_coroutine,
    name="evaluate_chapter_outline_sync",
    description=(
        "评估指定章节与大纲的同步性。"
        "必须显式传入 chapter_number；工具会内部读取大纲、角色、该章全文和元数据、历史章节梗概后一次性评估。"
    ),
    args_schema=EvaluateChapterOutlineSyncInput,
)


# ── 聚合评估工具：并行调用三个评估 ──


async def _evaluate_chapter_all_coroutine(
    chapter_number: int,
    evaluations: list[str] | None = None,
    config: RunnableConfig = None,
) -> str:
    """并行执行指定的评估任务，一次返回全部结果。"""
    from app.models.work_model import Chapter, Character, Work
    from app.services.work_service import WorkService

    if evaluations is None:
        evaluations = ["editor", "reader", "sync"]

    VALID_EVALS = {"editor", "reader", "sync"}
    invalid = [e for e in evaluations if e not in VALID_EVALS]
    if invalid:
        return f"无效的评估类型：{', '.join(invalid)}。合法值为：editor, reader, sync"
    if not evaluations:
        return "未指定任何评估类型。请在 evaluations 中传入至少一个：editor / reader / sync。"

    db = _get_db(config)
    work_id = _get_work_id(config)

    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"评估失败：作品 {work_id} 不存在。"

    chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
    if not chapter or not chapter.content:
        return f"评估失败：第{chapter_number}章正文不存在。"

    # 读取上下文（复用已有 helper）
    chapter_outline = WorkService._find_chapter_outline(work.outline_tree, chapter_number) or ""
    story_info = _outline_to_natural_text(work.outline_tree or {})
    previous_chapters = _read_previous_chapters_text(db, work_id, chapter_number)

    # 按需构建协程列表
    tasks = []
    eval_order = []  # 记录实际执行顺序，用于结果解析

    if "editor" in evaluations:
        tasks.append(_evaluate_as_editor_coroutine(
            chapter_content=chapter.content,
            story_info=story_info,
            chapter_outline=chapter_outline,
            previous_chapters=previous_chapters,
            config=config,
        ))
        eval_order.append("editor")

    if "reader" in evaluations:
        tasks.append(_evaluate_as_reader_coroutine(
            chapter_content=chapter.content,
            story_info=story_info,
            chapter_outline=chapter_outline,
            previous_chapters=previous_chapters,
            config=config,
        ))
        eval_order.append("reader")

    if "sync" in evaluations:
        tasks.append(_evaluate_chapter_outline_sync_coroutine(
            chapter_number=chapter_number,
            config=config,
        ))
        eval_order.append("sync")

    # 并行执行
    results = await asyncio.gather(*tasks)

    # 组装结果
    section_headers = {
        "editor": "编辑视角评估",
        "reader": "读者视角评估",
        "sync": "大纲同步性评估",
    }
    parts = []
    for eval_key, result in zip(eval_order, results):
        parts.append(f"## {section_headers[eval_key]}\n\n{result}")
    return "\n\n---\n\n".join(parts)


def _read_previous_chapters_text(db, work_id: str, chapter_number: int, limit: int = 3) -> str:
    """读取前几章正文，用于评估上下文。"""
    from app.models.work_model import Chapter

    prev_chapters = (
        db.query(Chapter)
        .filter_by(work_id=work_id)
        .filter(Chapter.chapter_number < chapter_number)
        .filter(Chapter.content != "")
        .order_by(Chapter.chapter_number.desc())
        .limit(limit)
        .all()
    )
    prev_chapters.reverse()
    if not prev_chapters:
        return ""
    parts = []
    for ch in prev_chapters:
        parts.append(f"--- 第{ch.chapter_number}章 {ch.title} ---\n{ch.content}")
    return "\n\n".join(parts)


evaluate_chapter_all = StructuredTool.from_function(
    func=None,
    coroutine=_evaluate_chapter_all_coroutine,
    name="evaluate_chapter_all",
    description=(
        "并行执行指定的评估任务（编辑视角 / 读者视角 / 大纲同步性），一次返回全部结果。"
        "只需传入 chapter_number，工具内部自动读取正文、大纲、前文等上下文。"
        "通过 evaluations 参数指定要执行哪些评估，默认全部执行。"
        "推荐优先使用此工具代替分别调用 evaluate_as_editor / evaluate_as_reader / evaluate_chapter_outline_sync。"
    ),
    args_schema=EvaluateChapterAllInput,
)


# ── 导出工具列表 ──

from app.services.supervisor.outline_tools import CHILD_TODO_TOOLS  # noqa: E402

_EVALUATION_CORE_TOOLS = [
    read_chapter_for_eval,
    read_chapter_outline_for_eval,
    read_previous_chapters_for_eval,
    evaluate_as_editor,
    evaluate_as_reader,
    evaluate_chapter_outline_sync,
    evaluate_chapter_all,
]

EVALUATION_TOOLS = [
    *CHILD_TODO_TOOLS,
    *_EVALUATION_CORE_TOOLS,
]
