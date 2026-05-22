"""OutlineAgent 工具集

大纲子 Agent 可调用的工具，封装大纲读取、角色查询、大纲生成/编辑和 diff 计算。
"""

from __future__ import annotations

import copy
import logging

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── Tool input schemas ──


class ReadOutlineInput(BaseModel):
    work_id: str = Field(description="作品ID")


class QueryOutlineCharactersInput(BaseModel):
    work_id: str = Field(description="作品ID")


class QueryOutlineRelatedChaptersInput(BaseModel):
    work_id: str = Field(description="作品ID")
    outline_query: str = Field(description="大纲片段查询词：可传节点ID（如 T1）或关键词（如 末日爆发/苏慕雪）")
    chapter_limit: int = Field(default=10, ge=1, le=100, description="返回章节上限")


class GenerateOutlineInput(BaseModel):
    idea: str = Field(description="故事创意/灵感描述")
    tags: list[str] = Field(default_factory=list, description="题材标签列表")


class EditOutlineInput(BaseModel):
    work_id: str = Field(description="作品ID")
    message: str = Field(description="编辑指令：用户想要对大纲做什么")


class CommitOrRollbackInput(BaseModel):
    work_id: str = Field(description="作品ID")
    action: str = Field(description="操作：commit 或 rollback")


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
    """获取 db_lock（threading.Lock 或 None）。"""
    return config.get("configurable", {}).get("db_lock")


def _with_lock(config: RunnableConfig):
    """返回一个上下文管理器：如果有 db_lock 则加锁，否则无操作。"""
    lock = _get_db_lock(config)
    if lock is not None:
        return lock
    from contextlib import nullcontext
    return nullcontext()


# ── 工具实现 ──


@tool(args_schema=ReadOutlineInput)
def read_outline(work_id: str, config: RunnableConfig) -> str:
    """读取作品当前的完整大纲信息。编辑大纲前必须先读取现有数据。"""
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
    foreshadowing = outline.get("foreshadowing", [])

    import json
    parts = [
        f"标题：{work.title}",
        f"类型：{story.get('genre', '未知')}",
        f"卷：{story.get('volume', '未知')}",
        f"时间线节点数：{len(timeline)}",
        f"伏笔数：{len(foreshadowing)}",
    ]
    if story.get("synopsis"):
        parts.append(f"简介：{story['synopsis']}")
    if timeline:
        parts.append(f"\n完整大纲：\n{json.dumps(outline, ensure_ascii=False, indent=2)[:3000]}")

    emit("query_result", {"source": "大纲读取", "summary": f"时间线 {len(timeline)} 节点"})
    return "\n".join(parts)


@tool(args_schema=QueryOutlineCharactersInput)
def query_outline_characters(work_id: str, config: RunnableConfig) -> str:
    """查询作品的所有角色设定。编辑大纲涉及角色变更时应先查询。"""
    from app.models.work_model import Character

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
        characters = db.query(Character).filter_by(work_id=work_id).order_by(
            Character.first_chapter.asc(), Character.created_at.asc()
        ).all()
    if not characters:
        return "该作品暂无角色设定。"

    parts = []
    for c in characters:
        fields = [f"【{c.name}】{c.role_type}"]
        for key, label in [
            ("gender", "性别"), ("age", "年龄"), ("personality", "性格"),
            ("background", "背景"), ("current_status", "状态"),
            ("first_chapter", "首次出场"),
        ]:
            val = getattr(c, key, None)
            if val:
                fields.append(f"{label}：{val}")
        parts.append("，".join(fields))

    emit("query_result", {"source": "角色查询", "summary": f"共 {len(characters)} 个角色"})
    return "\n".join(parts)


@tool(args_schema=QueryOutlineRelatedChaptersInput)
def query_outline_related_chapters(
    work_id: str,
    outline_query: str,
    chapter_limit: int,
    config: RunnableConfig,
) -> str:
    """级联查询：先匹配大纲片段，再回查关联章节（基于 chapter_metadata）。"""
    from app.models.work_model import Chapter, ChapterMetadata, Work

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    q = (outline_query or "").strip().lower()
    if not q:
        return "查询失败：outline_query 不能为空。"

    outline = work.outline_tree or {}
    timeline = outline.get("timeline", []) if isinstance(outline, dict) else []
    branches = outline.get("branches", []) if isinstance(outline, dict) else []
    characters = outline.get("characters", []) if isinstance(outline, dict) else []
    foreshadowing = outline.get("foreshadowing", []) if isinstance(outline, dict) else []

    matched_node_ids: set[str] = set()
    outline_hits: list[str] = []

    def _text_hit(parts: list[object]) -> bool:
        merged = " ".join(str(p or "") for p in parts).lower()
        return q in merged

    for node in timeline:
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        if q == node_id.lower() or _text_hit([
            node.get("id"),
            node.get("development_node"),
            node.get("summary"),
            node.get("time_node"),
        ]):
            matched_node_ids.add(node_id)
            outline_hits.append(f"timeline:{node_id} {node.get('development_node', '')}".strip())

    extra_keywords: set[str] = set()
    for item in branches:
        if _text_hit([item.get("id"), item.get("name"), item.get("summary"), item.get("description")]):
            label = item.get("name") or item.get("id") or "未命名分支"
            outline_hits.append(f"branch:{label}")
            extra_keywords.add(str(item.get("name") or "").strip())
    for item in characters:
        if _text_hit([item.get("name"), item.get("role_type"), item.get("background"), item.get("personality")]):
            name = str(item.get("name") or "").strip()
            if name:
                outline_hits.append(f"character:{name}")
                extra_keywords.add(name)
    for item in foreshadowing:
        if _text_hit([item.get("id"), item.get("content"), item.get("plant_node"), item.get("payoff_node")]):
            fid = str(item.get("id") or "unknown")
            outline_hits.append(f"foreshadow:{fid}")
            extra_keywords.add(str(item.get("content") or "").strip())

    with _with_lock(config):
        metadata_rows = db.query(ChapterMetadata).filter_by(work_id=work_id).all()
    if not metadata_rows:
        return "暂无章节元数据（chapter_metadata），暂时无法做级联查询。"

    matched: dict[int, dict] = {}
    keywords = [q] + [k.lower() for k in extra_keywords if k]
    for b in metadata_rows:
        score = 0
        reasons: list[str] = []

        timeline_ids = [
            str(link.get("id"))
            for link in (b.outline_links or [])
            if isinstance(link, dict) and str(link.get("type", "")).lower() == "timeline"
        ]
        node_hit_ids = [nid for nid in timeline_ids if str(nid) in matched_node_ids]
        if node_hit_ids:
            score += 5
            reasons.append(f"命中节点ID: {', '.join(node_hit_ids)}")

        searchable = " ".join([
            b.summary or "",
            " ".join(str(x) for x in (b.key_plot_points or [])),
            " ".join(str(x) for x in (b.foreshadows or [])),
            " ".join(str(x) for x in (b.facts or [])),
        ]).lower()
        text_hits = [kw for kw in keywords if kw and kw in searchable]
        if text_hits:
            score += min(3, len(text_hits))
            reasons.append(f"命中元数据关键词: {', '.join(text_hits[:3])}")

        if score > 0:
            matched[b.chapter_number] = {"score": score, "reasons": reasons}

    if not matched:
        return (
            f"未找到与「{outline_query}」相关的章节。"
            "可尝试传入更精确的 timeline 节点ID（如 T1/T2）或更具体的关键词。"
        )

    chapter_numbers = sorted(matched.keys())
    with _with_lock(config):
        chapters = (
            db.query(Chapter)
            .filter(Chapter.work_id == work_id, Chapter.chapter_number.in_(chapter_numbers))
            .all()
        )
    chapter_map = {c.chapter_number: c for c in chapters}

    ranked = sorted(matched.items(), key=lambda x: (-x[1]["score"], x[0]))[:chapter_limit]
    lines = [f"查询词：{outline_query}", f"命中大纲线索：{'; '.join(outline_hits[:8]) or '无'}", "关联章节："]
    for ch_no, meta in ranked:
        ch = chapter_map.get(ch_no)
        title = ch.title if ch else f"第{ch_no}章"
        status = ch.status if ch else "未知"
        reason = "；".join(meta["reasons"])
        lines.append(f"- 第{ch_no}章 {title}（{status}，score={meta['score']}）：{reason}")

    emit("query_result", {"source": "大纲关联章节", "summary": f"命中 {len(ranked)} 章"})
    return "\n".join(lines)


async def _generate_outline_coroutine(idea: str, tags: list[str], config: RunnableConfig) -> str:
    """从零生成大纲。"""
    from app.schemas.work_schema import OutlineQuickGenerateRequest
    from app.services.work_service import WorkService

    db = _get_db(config)
    emit = _get_emit(config)

    emit("stage_start", {"stage": "outline_create", "label": "创建大纲"})

    payload = OutlineQuickGenerateRequest(idea=idea, tags=tags)
    result = {}

    def capture_emit(event: str, data: dict):
        emit(event, data)
        if event == "outline_done":
            result["work_id"] = data.get("work_id")
            result["title"] = data.get("title")

    svc = WorkService()
    await svc.generate_outline_stream(payload, capture_emit)

    if not result.get("work_id"):
        return "大纲生成失败。"

    # 绑定 work_id 到 supervisor session
    session_id = config.get("configurable", {}).get("supervisor_session_id")
    if session_id:
        from app.models.agent_model import SupervisorSession
        from app.models.message_model import Message

        sess = db.query(SupervisorSession).filter_by(id=session_id).first()
        if sess:
            sess.work_id = result["work_id"]
            db.query(Message).filter(
                Message.session_id == session_id,
                Message.work_id.is_(None),
            ).update({"work_id": result["work_id"]}, synchronize_session=False)
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise

    return f"大纲创建成功。作品「{result.get('title', '')}」（work_id: {result.get('work_id', '')}）"


async def _edit_outline_coroutine(work_id: str, message: str, config: RunnableConfig) -> str:
    """编辑已有大纲。"""
    from app.models.work_model import Character, Work
    from app.services.diff_service import (
        compute_character_diff,
        compute_outline_diff,
        summarize_character_diff,
        summarize_outline_diff,
    )
    from app.services.work_service import WorkService

    db = _get_db(config)
    emit = _get_emit(config)
    auto_mode = config.get("configurable", {}).get("auto_mode", False)

    emit("stage_start", {"stage": "outline_edit", "label": "编辑大纲"})

    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    old_outline = copy.deepcopy(work.outline_tree) if work.outline_tree else {}
    chars = db.query(Character).filter_by(work_id=work_id).order_by(
        Character.first_chapter.asc(), Character.created_at.asc()
    ).all()
    old_characters = [_character_to_dict(c) for c in chars]

    try:
        svc = WorkService()
        response = await svc.chat_edit_async(
            work_id=work_id,
            user_message=message,
            history=[],
            db=db,
            dry_run=True,
        )

        dumped = response.model_dump(mode="json")
        new_outline = dumped.get("outline_tree") or {}

        new_chars = db.query(Character).filter_by(work_id=work_id).order_by(
            Character.first_chapter.asc(), Character.created_at.asc()
        ).all()
        new_characters = [_character_to_dict(c) for c in new_chars]

        outline_diff = compute_outline_diff(old_outline, new_outline)
        character_diff = compute_character_diff(old_characters, new_characters)

        outline_summary = summarize_outline_diff(outline_diff)
        character_summary = summarize_character_diff(character_diff)

        emit("outline_edit_diff", {
            "message": dumped["assistant_message"],
            "operations": dumped.get("operations") or [],
            "diff": outline_diff,
            "summary": outline_summary,
            "readonly": bool(auto_mode),
        })
        emit("character_edit_diff", {
            "diff": character_diff,
            "summary": character_summary,
            "readonly": bool(auto_mode),
        })

        return (
            f"大纲变更已生成"
            f"（大纲 +{outline_summary.get('total_added', 0)}/~{outline_summary.get('total_modified', 0)}/-{outline_summary.get('total_removed', 0)}"
            f"，角色 +{character_summary.get('total_added', 0)}/~{character_summary.get('total_modified', 0)}/-{character_summary.get('total_removed', 0)}）。"
            f"变更已暂存，请使用 commit_or_rollback 工具确认或回滚。"
        )

    except Exception as exc:
        db.rollback()
        return f"大纲编辑失败：{exc}"


@tool(args_schema=CommitOrRollbackInput)
def commit_or_rollback(work_id: str, action: str, config: RunnableConfig) -> str:
    """确认提交或回滚大纲变更。action 只能是 commit 或 rollback。"""
    db = _get_db(config)
    emit = _get_emit(config)

    if action == "commit":
        try:
            with _with_lock(config):
                db.commit()
        except Exception as exc:
            with _with_lock(config):
                db.rollback()
            return f"大纲变更提交失败：{exc!r}"
        emit("outline_edit_committed", {"work_id": work_id})
        return "大纲变更已提交。"
    elif action == "rollback":
        with _with_lock(config):
            db.rollback()
        emit("outline_edit_rolled_back", {"work_id": work_id})
        return "大纲变更已回滚。"
    else:
        return f"无效操作：{action}。请使用 commit 或 rollback。"


def _character_to_dict(c) -> dict:
    return {
        "name": c.name or "",
        "role_type": c.role_type or "",
        "gender": c.gender or "",
        "age": c.age or "",
        "appearance": c.appearance or "",
        "personality": c.personality or "",
        "background": c.background or "",
        "skills": c.skills or "",
        "current_status": c.current_status or "",
        "current_goal": c.current_goal or "",
        "first_chapter": c.first_chapter or 1,
    }


generate_outline = StructuredTool.from_function(
    func=None,
    coroutine=_generate_outline_coroutine,
    name="generate_outline",
    description="从零创建大纲。传入故事创意和题材标签，生成完整大纲并保存到数据库。",
    args_schema=GenerateOutlineInput,
)

edit_outline = StructuredTool.from_function(
    func=None,
    coroutine=_edit_outline_coroutine,
    name="edit_outline",
    description="编辑已有大纲。传入编辑指令，会执行 dry_run 修改并暂存变更。",
    args_schema=EditOutlineInput,
)


# ── 导出工具列表 ──

# 基础工具（两种模式共用）
_OUTLINE_BASE_TOOLS = [
    read_outline,
    query_outline_characters,
    query_outline_related_chapters,
    generate_outline,
    edit_outline,
]


def build_outline_tools(*, auto_mode: bool = True) -> list:
    """根据 auto_mode 构建大纲工具集。

    自动模式（auto_mode=True，默认）：包含 commit_or_rollback，LLM 自行决定提交或回滚。
    手动模式（auto_mode=False）：不含 commit_or_rollback，LLM 只做 dry_run，
    变更暂存在数据库事务中，由用户在 UI 确认后 commit/rollback。
    """
    tools = list(_OUTLINE_BASE_TOOLS)
    if auto_mode:
        tools.append(commit_or_rollback)
    return tools


# 向后兼容：默认包含 commit_or_rollback（自动模式）
OUTLINE_TOOLS = build_outline_tools(auto_mode=True)
