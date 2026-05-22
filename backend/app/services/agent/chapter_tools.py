"""ChapterAgent 工具集

章节撰写子 Agent 可调用的工具，封装大纲查询、上下文检索、正文生成和持久化操作。
"""

from __future__ import annotations

import json
import logging
import re
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


class QueryOutlineInput(BaseModel):
    work_id: str = Field(description="作品ID")


class QueryChapterOutlineInput(BaseModel):
    work_id: str = Field(description="作品ID")
    chapter_number: int = Field(description="章节号")


class QueryPreviousChaptersInput(BaseModel):
    work_id: str = Field(description="作品ID")
    chapter_number: int = Field(description="当前章节号，会查询此之前的章节")
    limit: int = Field(default=3, description="最多查询几章前文")


class QueryCharactersInput(BaseModel):
    work_id: str = Field(description="作品ID")


class QueryForeshadowingInput(BaseModel):
    work_id: str = Field(description="作品ID")


class GenerateChapterContentInput(BaseModel):
    chapter_number: int = Field(description="章节号")
    user_instruction: str = Field(description="用户的写作要求/指导意见")
    story_info: str = Field(description="作品信息（必填，不可为空）")
    outline_tree: str = Field(default="", description="完整大纲 JSON（可选，建议传入）")
    chapter_outline: str = Field(description="本章大纲（必填，不可为空）")
    thinking_notes: str = Field(default="", description="构思笔记（可选）")
    context_pack: str = Field(description="查询到的上下文资料（必填，不可为空）")
    previous_chapters: str = Field(description="前文回顾（第1章可为“暂无前文”）")


class SaveChapterInput(BaseModel):
    work_id: str = Field(description="作品ID")
    chapter_number: int = Field(description="章节号")
    title: str = Field(description="章节标题")
    content: str = Field(description="章节正文")


class UpdateCharactersAfterChapterInput(BaseModel):
    work_id: str = Field(description="作品ID")
    chapter_number: int = Field(description="章节号")
    chapter_content: str = Field(description="章节正文，用于分析角色状态变化")


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


def _get_db_lock(config: RunnableConfig):
    return config.get("configurable", {}).get("db_lock")


def _with_lock(config: RunnableConfig):
    lock = _get_db_lock(config)
    if lock is not None:
        return lock
    from contextlib import nullcontext
    return nullcontext()


def _word_count(text: str) -> int:
    return len(re.sub(r"\s", "", text))


# ── 工具实现 ──


@tool(args_schema=QueryOutlineInput)
def query_outline(work_id: str, config: RunnableConfig) -> str:
    """读取作品的完整大纲信息，包括故事设定、类型、卷信息等。"""
    from app.models.work_model import Work

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    outline = work.outline_tree or {}
    story = outline.get("story", {})
    timeline = outline.get("timeline", [])

    parts = [
        f"作品ID：{work_id}",
        f"标题：{work.title}",
        f"类型：{story.get('genre', '未知')}",
        f"卷：{story.get('volume', '未知')}",
        f"时间线节点数：{len(timeline)}",
    ]
    emit("query_result", {"source": "作品大纲", "summary": f"类型：{story.get('genre', '')}，节点数：{len(timeline)}"})
    return "\n".join(parts)


@tool(args_schema=QueryChapterOutlineInput)
def query_chapter_outline(work_id: str, chapter_number: int, config: RunnableConfig) -> str:
    """读取指定章节的大纲节点信息。"""
    from app.models.work_model import Work
    from app.services.work_service import WorkService

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    chapter_outline = WorkService._find_chapter_outline(work.outline_tree, chapter_number)
    emit("query_result", {"source": f"第{chapter_number}章大纲", "summary": chapter_outline or "未找到"})
    return chapter_outline or f"第{chapter_number}章未找到对应的大纲节点。"


@tool(args_schema=QueryPreviousChaptersInput)
def query_previous_chapters(work_id: str, chapter_number: int, limit: int, config: RunnableConfig) -> str:
    """查询当前章节之前的已写章节正文摘要，用于保持前后文连贯。"""
    from app.models.work_model import Chapter

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
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
        return "这是第一章，暂无前文。"

    parts = []
    for ch in prev_chapters:
        summary = ch.content[:800] + ("..." if len(ch.content) > 800 else "")
        parts.append(f"--- 第{ch.chapter_number}章 {ch.title} ---\n{summary}")
        emit("query_result", {"source": f"第{ch.chapter_number}章", "summary": summary[:200]})

    return "\n\n".join(parts)


@tool(args_schema=QueryCharactersInput)
def query_characters(work_id: str, config: RunnableConfig) -> str:
    """查询作品的所有角色设定信息，包括性格、状态、目的等。"""
    from app.models.work_model import Character

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
        characters = db.query(Character).filter_by(work_id=work_id).all()
    if not characters:
        return "该作品暂无角色设定。"

    parts = []
    for c in characters:
        fields = [f"【{c.name}】{c.role_type}"]
        for key, label in [
            ("gender", "性别"), ("age", "年龄"), ("personality", "性格"),
            ("background", "背景"), ("skills", "技能"),
            ("current_status", "当前状态"), ("current_goal", "当前目的"),
            ("last_location", "最后位置"), ("first_chapter", "首次出场"),
        ]:
            val = getattr(c, key, None)
            if val:
                fields.append(f"{label}：{val}")
        parts.append("，".join(fields))

    emit("query_result", {"source": "角色设定", "summary": f"共 {len(characters)} 个角色"})
    return "\n".join(parts)


@tool(args_schema=QueryForeshadowingInput)
def query_foreshadowing(work_id: str, config: RunnableConfig) -> str:
    """查询作品中的伏笔信息，包括埋设位置和回收位置。"""
    from app.models.work_model import Work

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    foreshadowing = work.outline_tree.get("foreshadowing", []) if work.outline_tree else []
    if not foreshadowing:
        return "暂无伏笔信息。"

    parts = []
    for f in foreshadowing:
        entry = f"伏笔 {f.get('id', '')}：{f.get('content', '')}（埋设于{f.get('plant_node', '')}，回收于{f.get('payoff_node', '')}）"
        parts.append(entry)
        emit("query_result", {"source": f"伏笔 {f.get('id', '')}", "summary": f.get('content', '')})

    return "\n".join(parts)


async def _generate_chapter_content_coroutine(
    chapter_number: int,
    user_instruction: str,
    story_info: str,
    chapter_outline: str,
    context_pack: str,
    previous_chapters: str,
    outline_tree: str = "",
    thinking_notes: str = "",
    config: RunnableConfig = None,
) -> str:
    """调用 LLM 生成章节正文，并在同一次工具调用中自动入库保存。"""
    from app.services.supervisor.sub_agent_base import get_llm
    from app.models.work_model import Chapter, Work
    from app.services.chapter_outline_sync_service import ChapterOutlineSyncService

    db = _get_db(config)
    emit = _get_emit(config)

    try:
        # 若 outline_tree 缺失，尝试从 story_info 中提取 work_id 并自动补齐完整大纲，
        # 避免提示词退化为“完整大纲（未提供）”。
        if not (outline_tree or "").strip():
            try:
                work_id_match = re.search(r"作品ID[：:]\s*([0-9a-fA-F-]{32,36})", story_info or "")
                if work_id_match:
                    work_id = work_id_match.group(1)
                    from app.models.work_model import Work

                    db = _get_db(config)
                    with _with_lock(config):
                        work = db.query(Work).filter_by(id=work_id).first()
                    if work and work.outline_tree:
                        outline_tree = json.dumps(work.outline_tree, ensure_ascii=False)
            except Exception:
                # 补齐失败不抛错，交由后续校验与提示处理
                pass

        # 关键上下文硬校验：缺失时拒绝生成，避免子 Agent 在低信息状态下反复重试。
        missing_fields: list[str] = []
        if not (user_instruction or "").strip():
            missing_fields.append("user_instruction")
        if not (story_info or "").strip():
            missing_fields.append("story_info")
        if not (chapter_outline or "").strip():
            missing_fields.append("chapter_outline")
        if not (context_pack or "").strip():
            missing_fields.append("context_pack")

        if missing_fields:
            msg = (
                "生成正文失败：缺少关键上下文参数 "
                f"{', '.join(missing_fields)}。"
                "请先补齐作品信息、本章大纲和上下文资料后再调用 generate_chapter_content。"
            )
            emit("error", {"message": msg})
            logger.warning(
                "generate_chapter_content rejected chapter=%s missing=%s",
                chapter_number,
                missing_fields,
            )
            return msg

        # 章节创建强约束：只能创建“当前最大章节 + 1”。
        # 该约束放在 generate_chapter_content 内部，避免同一章节被连续重复创建。
        work_id = None
        cfg = (config or {}).get("configurable", {})
        if cfg.get("work_id"):
            work_id = str(cfg.get("work_id"))
        if not work_id:
            work_id_match = re.search(r"作品ID[：:]\s*([0-9a-fA-F-]{32,36})", story_info or "")
            if work_id_match:
                work_id = work_id_match.group(1)

        if not work_id:
            msg = (
                "生成正文失败：无法解析 work_id，无法执行 n+1 章节校验。"
                "请在会话上下文或 story_info 中提供有效作品ID。"
            )
            emit("error", {"message": msg})
            return msg

        from app.models.work_model import Chapter

        with _with_lock(config):
            max_chapter = (
                db.query(Chapter)
                .filter_by(work_id=work_id)
                .order_by(Chapter.chapter_number.desc())
                .first()
            )
        expected_next = (max_chapter.chapter_number + 1) if max_chapter else 1
        if chapter_number != expected_next:
            msg = (
                "生成正文失败：章节创建必须严格按 n+1 顺序。"
                f"当前已存在至第{expected_next - 1}章，因此本次只能创建第{expected_next}章，"
                f"不能创建第{chapter_number}章。"
            )
            emit("error", {"message": msg})
            logger.warning(
                "generate_chapter_content rejected by n+1 work_id=%s chapter=%s expected=%s",
                work_id,
                chapter_number,
                expected_next,
            )
            return msg

        template = (PROMPT_DIR / "agent_write.txt").read_text(encoding="utf-8")
        prompt = PromptTemplate.from_template(template)
        llm = get_llm(temperature=0.7)
        chain = prompt | llm

        raw_output = ""
        async for chunk in chain.astream({
            "chapter_number": str(chapter_number),
            "story_info": story_info or "（未提供）",
            "outline_tree": outline_tree or "（未提供）",
            "chapter_outline": chapter_outline or "（未提供）",
            "chapter_title": f"第{chapter_number}章",
            "thinking_notes": thinking_notes or "（无构思笔记）",
            "context_pack": context_pack or "（无额外上下文）",
            "previous_chapters": previous_chapters or "（这是第一章，暂无前文）",
        }):
            text = chunk.content if hasattr(chunk, "content") else str(chunk)
            raw_output += text
            emit("write_stream", {"chunk": text})

        emit("write_done", {
            "word_count": _word_count(raw_output),
        })

        # 生成即保存：避免子 Agent 在“生成-检查-再生成”循环中因未落库导致反复调用生成工具。
        with _with_lock(config):
            chapter = db.query(Chapter).filter_by(
                work_id=work_id, chapter_number=chapter_number
            ).first()

            if chapter:
                chapter.title = chapter.title or f"第{chapter_number}章"
                chapter.content = raw_output
                chapter.status = "草稿"
            else:
                chapter = Chapter(
                    work_id=work_id,
                    chapter_number=chapter_number,
                    title=f"第{chapter_number}章",
                    content=raw_output,
                    status="草稿",
                )
                db.add(chapter)
                # 立即 flush，尽早暴露唯一键问题，避免同一 Session 内重复堆积 pending 插入。
                db.flush()

            work = db.query(Work).filter_by(id=work_id).first()
            if not work:
                db.rollback()
                msg = f"生成正文失败：作品 {work_id} 不存在。"
                emit("error", {"message": msg})
                return msg

            metadata_row = await ChapterOutlineSyncService.generate_and_persist(
                db,
                work=work,
                chapter=chapter,
            )
            db.commit()
            db.refresh(chapter)

        emit("saved", {
            "chapter_number": chapter_number,
            "title": chapter.title,
            "word_count": _word_count(raw_output),
            "source": "generate_chapter_content",
        })
        emit("chapter_metadata_generated", {
            "chapter_number": chapter_number,
            "summary": metadata_row.summary,
            "key_plot_points": metadata_row.key_plot_points,
            "outline_links": metadata_row.outline_links,
            "involved_characters": metadata_row.involved_characters,
            "foreshadows": metadata_row.foreshadows,
            "facts": metadata_row.facts,
            "updated_at": metadata_row.updated_at.isoformat() if metadata_row.updated_at else None,
        })

        return (
            f"{raw_output}\n\n"
            "【系统说明】本章已创建并保存，且已自动同步章节元数据。后续优化请调用编辑工具。"
        )
    except Exception as exc:
        # 关键：工具内异常必须回滚当前 Session，避免后续轮次继续使用脏事务。
        db.rollback()
        msg = f"生成正文失败：{exc!r}"
        emit("error", {"message": msg})
        logger.exception("generate_chapter_content failed chapter=%s", chapter_number)
        return msg


generate_chapter_content = StructuredTool.from_function(
    func=None,
    coroutine=_generate_chapter_content_coroutine,
    name="generate_chapter_content",
    description=(
        "调用 LLM 生成章节正文，并自动保存到数据库（草稿状态）。"
        "在调用前，应先用其他工具查询大纲、前文、角色等上下文信息。"
        "传入所有收集到的上下文和用户要求，返回完整的章节正文。"
    ),
    args_schema=GenerateChapterContentInput,
)


@tool(args_schema=SaveChapterInput)
def save_chapter(work_id: str, chapter_number: int, title: str, content: str, config: RunnableConfig) -> str:
    """将章节正文保存到数据库。仅在正文生成完毕且满意后调用。"""
    from app.models.work_model import Chapter

    db = _get_db(config)
    emit = _get_emit(config)

    try:
        with _with_lock(config):
            chapter = db.query(Chapter).filter_by(
                work_id=work_id, chapter_number=chapter_number
            ).first()

            if chapter:
                chapter.title = title or chapter.title
                chapter.content = content
                chapter.status = "草稿"
            else:
                chapter = Chapter(
                    work_id=work_id,
                    chapter_number=chapter_number,
                    title=title or f"第{chapter_number}章",
                    content=content,
                    status="草稿",
                )
                db.add(chapter)

            db.commit()
            db.refresh(chapter)
    except Exception as exc:
        with _with_lock(config):
            db.rollback()
        logger.exception("save_chapter failed work_id=%s chapter=%s", work_id, chapter_number)
        return f"保存第{chapter_number}章失败：{exc!r}"

    wc = _word_count(content)
    emit("saved", {
        "chapter_number": chapter_number,
        "title": chapter.title,
        "word_count": wc,
    })

    return f"第{chapter_number}章「{chapter.title}」已保存，字数：{wc}"


async def _update_characters_after_chapter_coroutine(
    work_id: str,
    chapter_number: int,
    chapter_content: str,
    config: RunnableConfig = None,
) -> str:
    """分析章节正文，更新角色的当前状态、目的和位置。"""
    from pydantic import BaseModel as PydanticBase

    from app.models.work_model import Character
    from app.services.supervisor.sub_agent_base import get_llm

    class CharacterUpdate(PydanticBase):
        name: str = Field(description="角色名")
        current_status: str = Field(default="", description="新状态")
        current_goal: str = Field(default="", description="新目的")
        last_location: str = Field(default="", description="新位置")

    class CharacterUpdatesResult(PydanticBase):
        character_updates: list[CharacterUpdate] = Field(default_factory=list)

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
        characters = db.query(Character).filter_by(work_id=work_id).all()
    if not characters:
        return "无角色需要更新。"

    char_list = []
    for c in characters:
        char_list.append(f"- {c.name}（{c.role_type}）：当前状态={c.current_status}，目的={c.current_goal}，最后位置={c.last_location}")

    char_text = "\n".join(char_list)

    template = (PROMPT_DIR / "agent_update_characters.txt").read_text(encoding="utf-8")
    prompt = PromptTemplate.from_template(template)
    llm = get_llm(temperature=0.3, streaming=False)
    structured_llm = llm.with_structured_output(CharacterUpdatesResult)

    chain = prompt | structured_llm

    try:
        result = await chain.ainvoke({
            "chapter_number": str(chapter_number),
            "chapter_title": f"第{chapter_number}章",
            "chapter_content": chapter_content[:3000],
            "characters": char_text,
        })

        updates = result.character_updates if result else []

        updated_names = []
        for upd in updates:
            char_name = upd.name
            char = next((c for c in characters if c.name == char_name), None)
            if not char:
                continue
            if upd.current_status:
                char.current_status = upd.current_status
            if upd.current_goal:
                char.current_goal = upd.current_goal
            if upd.last_location:
                char.last_location = upd.last_location
            char.last_chapter = chapter_number
            updated_names.append(char_name)

        with _with_lock(config):
            db.commit()
        emit("characters_updated", {
            "message": f"已更新 {len(updated_names)} 个角色状态",
            "updated": updated_names,
        })
        return f"已更新 {len(updated_names)} 个角色状态：{'、'.join(updated_names)}" if updated_names else "无需更新角色状态。"

    except Exception as exc:
        with _with_lock(config):
            db.rollback()
        return f"角色状态更新跳过：{exc}"


update_characters_after_chapter = StructuredTool.from_function(
    func=None,
    coroutine=_update_characters_after_chapter_coroutine,
    name="update_characters_after_chapter",
    description=(
        "分析已保存的章节正文，自动更新相关角色的当前状态、目的和位置。"
        "应在章节正文已保存后调用（可由 generate_chapter_content 自动保存，或由 save_chapter 手动保存）。"
    ),
    args_schema=UpdateCharactersAfterChapterInput,
)


# ── 导出工具列表 ──

CHAPTER_TOOLS = [
    query_outline,
    query_chapter_outline,
    query_previous_chapters,
    query_characters,
    query_foreshadowing,
    generate_chapter_content,
    save_chapter,
    update_characters_after_chapter,
]
