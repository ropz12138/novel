import json
import logging
import time
import asyncio
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from langchain_core.tools import StructuredTool
from app.core.deepseek_llm import DeepSeekChatOpenAI
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.models.work_model import Chapter, ChapterMetadata, Character, Work
from app.services.agent_log_service import log_event, new_session_id
from app.schemas.work_schema import (
    BranchNode,
    ChapterDeleteLastResponse,
    ChapterIntelOut,
    ChapterOut,
    ChapterUpdateRequest,
    ChatEditResponse,
    CharacterBrief,
    CharacterDetail,
    ForeshadowingNode,
    OutlineQuickGenerateRequest,
    OutlineTreeData,
    StoryInfo,
    TimelineNode,
    WorkOut,
)

PROMPT_DIR = Path(__file__).resolve().parent / "prompt_templates"

logger = logging.getLogger(__name__)


_OUTLINE_GENERATION_CTX: ContextVar[dict[str, Any] | None] = ContextVar(
    "outline_generation_ctx",
    default=None,
)

_QUOTE_CONSTRAINT = (
    "【JSON 约束】所有字符串值中禁止使用英文双引号（\"），"
    "如需引用请使用中文双引号（\u201c\u201d）或单引号。\n"
)


def _llm_message_text(ai_msg) -> str:
    raw = getattr(ai_msg, "content", "") or ""
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        raw = "".join(parts)
    return raw.strip()


# DEPRECATED: _ChatEditOutput is no longer used by chat_edit / chat_edit_async.
# These methods now use native Tool-Calling; operations are collected from AIMessage.tool_calls.
class _ChatEditOutput(BaseModel):
    assistant_message: str
    operations: list[dict]


class _SubmitOutlineInput(OutlineTreeData):
    """Tool-call payload for initial outline generation."""


def _empty_outline(story: dict | None = None) -> dict:
    return {
        "story": story or {},
        "outline": {"macro_phases": [], "core_characters": [], "ending": {}},
        "meso": {"meso_stages": []},
        "micro": {"micro_scenes": []},
        "foreshadowing": [],
        "characters": [],
        "character_links": [],
    }


def _outline_ctx() -> dict[str, Any] | None:
    return _OUTLINE_GENERATION_CTX.get()


def _coerce_character_age(items: list[dict]) -> list[dict]:
    normalized = []
    for item in items or []:
        if isinstance(item, dict):
            copied = dict(item)
            if "age" in copied and copied["age"] is not None:
                copied["age"] = str(copied["age"])
            normalized.append(copied)
        else:
            normalized.append(item)
    return normalized


def _ctx_work(ctx: dict[str, Any]) -> Work:
    db: Session = ctx["db"]
    work_id = ctx.get("work_id")
    work = db.query(Work).filter_by(id=work_id).first() if work_id else None
    if not work:
        raise ValueError("大纲生成工具缺少已创建的作品上下文，请先调用 submit_story。")
    return work


def _commit_outline_section(ctx: dict[str, Any], section: str, value: Any) -> Work:
    db: Session = ctx["db"]
    work = _ctx_work(ctx)
    outline = dict(work.outline_tree or _empty_outline())
    outline[section] = value
    work.outline_tree = outline
    flag_modified(work, "outline_tree")
    db.commit()
    db.refresh(work)
    return work


def _upsert_outline_characters(ctx: dict[str, Any], characters: list[dict]) -> None:
    db: Session = ctx["db"]
    work = _ctx_work(ctx)
    existing = {
        c.name: c
        for c in db.query(Character).filter_by(work_id=work.id).all()
    }
    for char_data in characters:
        name = char_data.get("name", "")
        if not name:
            continue
        char = existing.get(name)
        payload = {
            "role_type": char_data.get("role_type", "配角"),
            "gender": char_data.get("gender", ""),
            "age": char_data.get("age", ""),
            "appearance": char_data.get("appearance", ""),
            "personality": char_data.get("personality", ""),
            "background": char_data.get("background", ""),
            "skills": char_data.get("skills", ""),
            "current_status": char_data.get("current_status", "存活"),
            "current_goal": char_data.get("current_goal", ""),
            "first_appearance_stage": char_data.get("first_appearance_stage", "M1"),
            "last_chapter": char_data.get("last_chapter"),
        }
        if char:
            for key, value in payload.items():
                setattr(char, key, value)
        else:
            db.add(Character(work_id=work.id, name=name, **payload))


def _submit_outline_tool(**kwargs) -> str:
    """Accept the complete generated outline as structured tool arguments."""
    ctx = _outline_ctx()
    if not ctx:
        return "outline_received"
    db: Session = ctx["db"]
    outline = OutlineTreeData.model_validate(kwargs).model_dump(mode="json")
    story = outline["story"]
    work = Work(
        user_id=ctx["user_id"],
        title=story["title"],
        genre=story["genre"],
        idea=ctx["idea"],
        tags=ctx["tags_list"],
        outline_tree=outline,
        status="草稿",
    )
    db.add(work)
    db.flush()
    ctx["work_id"] = work.id
    _upsert_outline_characters(ctx, outline.get("characters", []))
    db.commit()
    return "outline_persisted"


SUBMIT_OUTLINE_TOOL = StructuredTool.from_function(
    func=_submit_outline_tool,
    name="submit_outline",
    description="提交完整小说大纲。必须一次性提供 story、timeline、branches、foreshadowing、characters。",
    args_schema=_SubmitOutlineInput,
)


class _SubmitStoryInput(BaseModel):
    story: StoryInfo


class _SubmitTimelineInput(BaseModel):
    timeline: list[TimelineNode]


class _SubmitCharacterBriefsInput(BaseModel):
    briefs: list[CharacterBrief]


class _SubmitCharacterDetailsInput(BaseModel):
    characters: list[CharacterDetail]


class _SubmitBranchesInput(BaseModel):
    branches: list[BranchNode]


class _SubmitForeshadowingInput(BaseModel):
    foreshadowing: list[ForeshadowingNode]


class _SubmitCharacterLinksInput(BaseModel):
    character_links: list[dict]


# ── 三层大纲架构输入模型 ──


class MacroPhase(BaseModel):
    id: str = Field(description="阶段ID，如 P1、P2")
    name: str = Field(description="阶段名称，如：新手村、第一卷、序章")
    goal: str = Field(description="阶段目标，主角在这个阶段要达成什么")
    core_setting: str = Field(description="核心设定，这个阶段的关键世界观/规则/势力")
    ending_direction: str = Field(default="", description="结局方向，这个阶段结束时的状态/转折（可选）")
    chapter_range: list[int] = Field(default_factory=lambda: [1, 50], description="预计章节范围 [开始, 结束]")


class CoreCharacterBrief(BaseModel):
    name: str = Field(description="角色名")
    role_type: str = Field(description="主角/反派/导师等")
    brief: str = Field(description="一句话角色定位")


class MesoStage(BaseModel):
    id: str = Field(description="阶段ID，如 M1、M2")
    macro_phase_id: str = Field(description="关联的大纲阶段ID")
    name: str = Field(description="阶段名称，如：新手村副本、城市案件")
    type: str = Field(description="类型：副本/地图/案件/赛事/战争/感情阶段/商业阶段")
    cause: str = Field(description="起因，为什么开始这个阶段")
    conflict: str = Field(description="冲突，主要矛盾是什么")
    key_characters: list[str] = Field(default_factory=list, description="关键人物")
    twist: str = Field(default="", description="反转，剧情转折点")
    climax: str = Field(default="", description="高潮，最激烈的冲突")
    reward: str = Field(default="", description="收益，完成后的收获")
    chapter_range: list[int] = Field(default_factory=lambda: [1, 10], description="预计章节范围 [开始, 结束]")

class _SubmitMacroOutlineInput(BaseModel):
    story: StoryInfo
    macro_phases: list[MacroPhase]
    core_characters: list[CoreCharacterBrief]
    meso_stages: list[MesoStage] = Field(default_factory=list, description="中纲阶段（可选，与宏观阶段一起生成）")
    ending: dict = Field(default_factory=dict, description="整体结局方向（可选）")




class _SubmitMesoOutlineInput(BaseModel):
    meso_doc: str = Field(description="中纲自然语言文档：当前阶段的详细信息，包含剧情走向、角色安排、情感脉络等")


class MicroScene(BaseModel):
    id: str = Field(description="场景ID，如 S1、S2")
    meso_stage_id: str = Field(description="关联的中纲阶段ID")
    chapter_number: int = Field(description="章节号")
    scene_number: int = Field(default=1, description="场景号")
    characters: list[str] = Field(default_factory=list, description="出场人物")
    location: str = Field(default="", description="地点")
    conflict: str = Field(default="", description="冲突")
    info_points: list[str] = Field(default_factory=list, description="信息点")
    emotion_points: list[str] = Field(default_factory=list, description="爽点/笑点/情绪点")
    hook: str = Field(default="", description="结尾钩子")


class _SubmitMicroOutlineInput(BaseModel):
    micro_doc: str = Field(description="小纲自然语言文档：近几章的场景安排、出场人物、冲突设计、情感节奏等")


def _submit_story_tool(**kwargs) -> str:
    ctx = _outline_ctx()
    if not ctx:
        return "story_received"
    db: Session = ctx["db"]
    story = _SubmitStoryInput.model_validate(kwargs).story.model_dump(mode="json")
    work_id = ctx.get("work_id")
    work = db.query(Work).filter_by(id=work_id).first() if work_id else None
    if not work:
        work = Work(
            user_id=ctx["user_id"],
            title=story["title"],
            genre=story["genre"],
            idea=ctx["idea"],
            tags=ctx["tags_list"],
            outline_tree=_empty_outline(story),
            status="草稿",
        )
        db.add(work)
        db.flush()
        ctx["work_id"] = work.id
    else:
        outline = dict(work.outline_tree or _empty_outline())
        outline["story"] = story
        work.outline_tree = outline
        work.title = story["title"]
        work.genre = story["genre"]
        flag_modified(work, "outline_tree")
    db.commit()
    return "story_persisted"


def _submit_timeline_tool(**kwargs) -> str:
    ctx = _outline_ctx()
    if not ctx:
        return "timeline_received"
    timeline = _SubmitTimelineInput.model_validate(kwargs).model_dump(mode="json")["timeline"]
    _commit_outline_section(ctx, "timeline", timeline)
    return "timeline_persisted"


def _submit_character_briefs_tool(**kwargs) -> str:
    ctx = _outline_ctx()
    if not ctx:
        return "character_briefs_received"
    if isinstance(kwargs.get("briefs"), list):
        kwargs = dict(kwargs)
        kwargs["briefs"] = _coerce_character_age(kwargs["briefs"])
    briefs = _SubmitCharacterBriefsInput.model_validate(kwargs).model_dump(mode="json")["briefs"]
    ctx["briefs"] = briefs
    _commit_outline_section(ctx, "character_briefs", briefs)
    return "character_briefs_persisted"


def _submit_character_details_tool(**kwargs) -> str:
    ctx = _outline_ctx()
    if not ctx:
        return "character_details_received"
    if isinstance(kwargs.get("characters"), list):
        kwargs = dict(kwargs)
        kwargs["characters"] = _coerce_character_age(kwargs["characters"])
    details = _SubmitCharacterDetailsInput.model_validate(kwargs).model_dump(mode="json")["characters"]
    detail_map = {d["name"]: d for d in details}
    all_details = {d["name"]: d for d in ctx.get("character_details", [])}
    all_details.update(detail_map)
    ctx["character_details"] = list(all_details.values())

    characters = []
    for brief in ctx.get("briefs", []):
        detail = all_details.get(brief["name"], {})
        characters.append({
            "name": brief["name"],
            "role_type": brief.get("role_type", "配角"),
            "gender": brief.get("gender", ""),
            "age": brief.get("age", ""),
            "appearance": detail.get("appearance", ""),
            "personality": detail.get("personality", ""),
            "background": detail.get("background", ""),
            "skills": detail.get("skills", ""),
            "current_status": detail.get("current_status", "存活"),
            "current_goal": detail.get("current_goal", ""),
            "first_appearance_stage": (
                detail.get("first_appearance_stage")
                or brief.get("first_appearance_stage", "M1")
            ),
        })
    _commit_outline_section(ctx, "characters", characters)
    _upsert_outline_characters(ctx, characters)
    ctx["characters"] = characters
    ctx["db"].commit()
    return "character_details_persisted"


def _submit_branches_tool(**kwargs) -> str:
    ctx = _outline_ctx()
    if not ctx:
        return "branches_received"
    branches = _SubmitBranchesInput.model_validate(kwargs).model_dump(mode="json")["branches"]
    _commit_outline_section(ctx, "branches", branches)
    return "branches_persisted"


def _submit_foreshadowing_tool(**kwargs) -> str:
    ctx = _outline_ctx()
    if not ctx:
        return "foreshadowing_received"
    foreshadowing = _SubmitForeshadowingInput.model_validate(kwargs).model_dump(mode="json")["foreshadowing"]
    _commit_outline_section(ctx, "foreshadowing", foreshadowing)
    return "foreshadowing_persisted"


def _submit_character_links_tool(**kwargs) -> str:
    ctx = _outline_ctx()
    if not ctx:
        return "character_links_received"
    character_links = _SubmitCharacterLinksInput.model_validate(kwargs).model_dump(mode="json")["character_links"]
    _commit_outline_section(ctx, "character_links", character_links)
    return "character_links_persisted"


def _submit_macro_outline_tool(**kwargs) -> str:
    """提交大纲（Macro Outline）"""
    ctx = _outline_ctx()
    if not ctx:
        return "macro_outline_received"
    db: Session = ctx["db"]
    
    # 解析输入
    story = kwargs.get("story", {})
    macro_phases = kwargs.get("macro_phases", [])
    core_characters = kwargs.get("core_characters", [])
    ending = kwargs.get("ending", {})
    meso_stages = kwargs.get("meso_stages", [])

    # 校验：关键数据不可为空
    if not story or not story.get("title"):
        raise ValueError("story 缺失或未包含 title，无法提交大纲。")
    if not macro_phases:
        raise ValueError("macro_phases 为空，无法提交大纲。至少需要一个宏观阶段。")
    if not core_characters:
        raise ValueError("core_characters 为空，无法提交大纲。至少需要一个核心角色。")
    
    # 创建或更新作品
    work_id = ctx.get("work_id")
    work = db.query(Work).filter_by(id=work_id).first() if work_id else None
    if not work:
        work = Work(
            user_id=ctx["user_id"],
            title=story.get("title", "未命名作品"),
            genre=story.get("genre", "未分类"),
            idea=ctx["idea"],
            tags=ctx["tags_list"],
            outline_tree=_empty_outline(story),
            status="草稿",
        )
        db.add(work)
        db.flush()
        ctx["work_id"] = work.id
    
    # 更新大纲结构
    outline = dict(work.outline_tree or _empty_outline())
    outline["story"] = story
    outline["outline"] = {
        "story": story,
        "macro_phases": macro_phases,
        "core_characters": core_characters,
        "ending": ending,
    }
    if meso_stages:
        outline["meso"] = {"meso_stages": meso_stages}
    work.outline_tree = outline
    work.title = story.get("title", work.title)
    work.genre = story.get("genre", work.genre)
    flag_modified(work, "outline_tree")
    db.commit()
    return "macro_outline_persisted"


def _submit_meso_outline_tool(**kwargs) -> str:
    """提交中纲（Meso Outline）：写入自然语言文档 meso_doc"""
    ctx = _outline_ctx()
    if not ctx:
        return "meso_outline_received"
    meso_doc = kwargs.get("meso_doc", "")
    if not meso_doc or not meso_doc.strip():
        raise ValueError("meso_doc 为空，无法提交中纲。需要提供自然语言的中纲文档。")
    db: Session = ctx["db"]
    work_id = ctx.get("work_id")
    work = db.query(Work).filter_by(id=work_id).first() if work_id else None
    if not work:
        raise ValueError("作品不存在，无法提交中纲。")
    work.meso_doc = meso_doc
    flag_modified(work, "meso_doc")
    db.commit()
    return "meso_outline_persisted"


def _submit_micro_outline_tool(**kwargs) -> str:
    """提交小纲（Micro Outline）：写入自然语言文档 micro_doc"""
    ctx = _outline_ctx()
    if not ctx:
        return "micro_outline_received"
    micro_doc = kwargs.get("micro_doc", "")
    if not micro_doc or not micro_doc.strip():
        raise ValueError("micro_doc 为空，无法提交小纲。需要提供自然语言的小纲文档。")
    db: Session = ctx["db"]
    work_id = ctx.get("work_id")
    work = db.query(Work).filter_by(id=work_id).first() if work_id else None
    if not work:
        raise ValueError("作品不存在，无法提交小纲。")
    work.micro_doc = micro_doc
    flag_modified(work, "micro_doc")
    db.commit()
    return "micro_outline_persisted"


SUBMIT_MACRO_OUTLINE_TOOL = StructuredTool.from_function(
    func=_submit_macro_outline_tool,
    name="submit_macro_outline",
    description="提交大纲（Macro Outline）：包含 story、macro_phases、core_characters、ending。",
    args_schema=_SubmitMacroOutlineInput,
)

SUBMIT_MESO_OUTLINE_TOOL = StructuredTool.from_function(
    func=_submit_meso_outline_tool,
    name="submit_meso_outline",
    description="提交中纲（Meso Outline）：包含 meso_stages。",
    args_schema=_SubmitMesoOutlineInput,
)

SUBMIT_MICRO_OUTLINE_TOOL = StructuredTool.from_function(
    func=_submit_micro_outline_tool,
    name="submit_micro_outline",
    description="提交小纲（Micro Outline）：包含 micro_scenes。",
    args_schema=_SubmitMicroOutlineInput,
)


SUBMIT_STORY_TOOL = StructuredTool.from_function(
    func=_submit_story_tool,
    name="submit_story",
    description="提交作品基础信息 story。",
    args_schema=_SubmitStoryInput,
)

SUBMIT_TIMELINE_TOOL = StructuredTool.from_function(
    func=_submit_timeline_tool,
    name="submit_timeline",
    description="提交主线时间线 timeline。",
    args_schema=_SubmitTimelineInput,
)

SUBMIT_CHARACTER_BRIEFS_TOOL = StructuredTool.from_function(
    func=_submit_character_briefs_tool,
    name="submit_character_briefs",
    description="提交角色骨架列表：所有角色的 name/role_type/gender/age/first_appearance_stage/brief。",
    args_schema=_SubmitCharacterBriefsInput,
)

SUBMIT_CHARACTER_DETAILS_TOOL = StructuredTool.from_function(
    func=_submit_character_details_tool,
    name="submit_character_details",
    description="提交本批次角色的详细信息。",
    args_schema=_SubmitCharacterDetailsInput,
)

SUBMIT_BRANCHES_TOOL = StructuredTool.from_function(
    func=_submit_branches_tool,
    name="submit_branches",
    description="提交支线列表 branches。",
    args_schema=_SubmitBranchesInput,
)

SUBMIT_FORESHADOWING_TOOL = StructuredTool.from_function(
    func=_submit_foreshadowing_tool,
    name="submit_foreshadowing",
    description="提交伏笔列表 foreshadowing。",
    args_schema=_SubmitForeshadowingInput,
)

SUBMIT_CHARACTER_LINKS_TOOL = StructuredTool.from_function(
    func=_submit_character_links_tool,
    name="submit_character_links",
    description="提交角色-剧情关系表 character_links。",
    args_schema=_SubmitCharacterLinksInput,
)


def _parse_outline_from_tool_call(ai_msg) -> dict:
    tool_calls = _extract_tool_calls(ai_msg)
    for call in tool_calls:
        if call.get("name") != "submit_outline":
            continue
        args = call.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError("submit_outline tool args must be an object")
        _submit_outline_tool(**args)
        return args
    raise ValueError("LLM did not call submit_outline")


def _extract_tool_calls(ai_msg) -> list[dict]:
    """Return tool calls exposed on AIMessage.tool_calls only."""
    return list(getattr(ai_msg, "tool_calls", None) or [])


def _parse_section_from_tool_call(ai_msg, *, tool_name: str, field_name: str):
    submit_handlers = {
        "submit_story": _submit_story_tool,
        "submit_timeline": _submit_timeline_tool,
        "submit_character_briefs": _submit_character_briefs_tool,
        "submit_character_details": _submit_character_details_tool,
        "submit_branches": _submit_branches_tool,
        "submit_foreshadowing": _submit_foreshadowing_tool,
        "submit_character_links": _submit_character_links_tool,
        "submit_macro_outline": _submit_macro_outline_tool,
        "submit_meso_outline": _submit_meso_outline_tool,
        "submit_micro_outline": _submit_micro_outline_tool,
    }
    # 三层大纲：field_name 到实际 schema 字段的映射
    _field_aliases = {
        "macro_outline": None,  # macro_outline 返回整个 args
        "meso_outline": "meso_stages",
        "micro_outline": "micro_scenes",
    }
    tool_calls = _extract_tool_calls(ai_msg)
    for call in tool_calls:
        if call.get("name") != tool_name:
            continue
        args = call.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError(f"{tool_name} tool args must be an object")
        if tool_name == "submit_character_briefs" and isinstance(args.get(field_name), list):
            args = dict(args)
            args[field_name] = _coerce_character_age(args[field_name])
        if tool_name == "submit_character_details" and isinstance(args.get(field_name), list):
            args = dict(args)
            args[field_name] = _coerce_character_age(args[field_name])

        # 确定要返回的字段
        actual_field = _field_aliases.get(field_name, field_name)
        if actual_field is None:
            # macro_outline: 返回整个 args（包含 story, macro_phases, core_characters, ending）
            handler = submit_handlers.get(tool_name)
            if handler:
                handler(**args)
            return args
        if actual_field not in args:
            raise ValueError(f"{tool_name} missing field: {actual_field}")
        handler = submit_handlers.get(tool_name)
        if handler:
            handler(**args)
        return args[actual_field]

    raise ValueError(f"LLM did not call {tool_name}")


class WorkService:
    def __init__(self) -> None:
        model_conf = settings.get_model_config()
        base_model = DeepSeekChatOpenAI(
            model=settings.default_model,
            api_key=model_conf["api_key"],
            base_url=model_conf["base_url"],
            temperature=0.7,
            request_timeout=(15, 180),
            max_retries=0,
        )

        # 大纲生成使用默认模型（由 config.json 的 default_model 控制）
        outline_model_name = settings.default_model
        outline_conf = settings.get_model_config(outline_model_name)
        outline_model = DeepSeekChatOpenAI(
            model=outline_model_name,
            api_key=outline_conf["api_key"],
            base_url=outline_conf["base_url"],
            temperature=0.7,
            request_timeout=(15, 180),
            max_retries=0,
        )

        # 429 fallback
        if settings.fallback_model:
            from app.core.deepseek_llm import FallbackLLM
            fb_conf = settings.get_model_config(settings.fallback_model)
            fb = DeepSeekChatOpenAI(
                model=settings.fallback_model,
                api_key=fb_conf["api_key"],
                base_url=fb_conf["base_url"],
                temperature=0.7,
                request_timeout=(15, 180),
                max_retries=0,
            )
            base_model = FallbackLLM(base_model, fb)
            outline_model = FallbackLLM(outline_model, DeepSeekChatOpenAI(
                model=settings.fallback_model,
                api_key=fb_conf["api_key"],
                base_url=fb_conf["base_url"],
                temperature=0.7,
                request_timeout=(15, 180),
                max_retries=0,
            ))

        self.chat_model = base_model

        self.outline_tool_llm = outline_model.bind_tools(
            [SUBMIT_OUTLINE_TOOL],
            max_tokens=131072,
        )
        self.outline_story_llm = outline_model.bind_tools(
            [SUBMIT_STORY_TOOL],
            max_tokens=131072,
        )
        self.outline_timeline_llm = outline_model.bind_tools(
            [SUBMIT_TIMELINE_TOOL],
            max_tokens=131072,
        )
        self.outline_character_briefs_llm = outline_model.bind_tools(
            [SUBMIT_CHARACTER_BRIEFS_TOOL],
            max_tokens=131072,
        )
        self.outline_character_details_llm = outline_model.bind_tools(
            [SUBMIT_CHARACTER_DETAILS_TOOL],
            max_tokens=131072,
        )
        self.outline_branches_llm = outline_model.bind_tools(
            [SUBMIT_BRANCHES_TOOL],
            max_tokens=131072,
        )
        self.outline_foreshadowing_llm = outline_model.bind_tools(
            [SUBMIT_FORESHADOWING_TOOL],
            max_tokens=131072,
        )
        self.outline_character_links_llm = outline_model.bind_tools(
            [SUBMIT_CHARACTER_LINKS_TOOL],
            max_tokens=131072,
        )
        # 三层大纲 LLM 实例
        self.outline_macro_llm = outline_model.bind_tools(
            [SUBMIT_MACRO_OUTLINE_TOOL],
            max_tokens=131072,
        )
        self.outline_meso_llm = outline_model.bind_tools(
            [SUBMIT_MESO_OUTLINE_TOOL],
            max_tokens=131072,
        )
        self.outline_micro_llm = outline_model.bind_tools(
            [SUBMIT_MICRO_OUTLINE_TOOL],
            max_tokens=131072,
        )
        # NOTE: chat_edit_model (with_structured_output) removed — chat_edit_async
        # now uses native Tool-Calling via self.chat_model.bind_tools(ALL_OUTLINE_TOOLS).

    def _read_prompt(self, file_name: str) -> str:
        path = PROMPT_DIR / file_name
        return path.read_text(encoding="utf-8")

    async def _generate_outline_sections(
        self,
        idea: str,
        tags: str,
        emit=None,
        db: Session | None = None,
        user_id: str | None = None,
        tags_list: list[str] | None = None,
    ) -> dict:
        token = None
        if db is not None and user_id is not None:
            token = _OUTLINE_GENERATION_CTX.set({
                "db": db,
                "user_id": user_id,
                "idea": idea,
                "tags_list": tags_list or [],
            })

        def _status(phase: str, message: str):
            if emit:
                emit("outline_status", {"phase": phase, "message": message})

        def _compact(items: object, limit: int = 8) -> str:
            if isinstance(items, list):
                slim = items[:limit]
                return json.dumps(slim, ensure_ascii=False)
            if isinstance(items, dict):
                return json.dumps(items, ensure_ascii=False)
            return json.dumps(items, ensure_ascii=False)

        async def _ainvoke_section(llm, prompt_text: str, tool_name: str, field_name: str):
            attempts = 3
            last_exc: Exception | None = None
            for i in range(1, attempts + 1):
                retry_prompt = prompt_text
                if i > 1:
                    retry_prompt = (
                        f"{prompt_text}\n\n"
                        "【强约束】你上一次输出未被系统识别。"
                        "这一次只允许输出工具调用，不允许解释性文字。"
                        f"必须且只调用 {tool_name}，并确保 {field_name} 是合法 JSON。"
                    )
                try:
                    msg = await llm.ainvoke([("human", retry_prompt)])
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    logger.warning(
                        "outline section llm invoke failed tool=%s attempt=%s/%s err=%s",
                        tool_name, i, attempts, exc,
                    )
                    if emit and i < attempts:
                        emit(
                            "outline_status",
                            {"phase": "retrying", "message": f"{tool_name} 调用失败，正在重试（{i}/{attempts - 1}）..."},
                        )
                    continue
                try:
                    return _parse_section_from_tool_call(msg, tool_name=tool_name, field_name=field_name)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    logger.warning(
                        "outline section tool-call parse failed tool=%s attempt=%s/%s text_preview=%r tool_calls=%r err=%s",
                        tool_name,
                        i,
                        attempts,
                        _llm_message_text(msg),
                        getattr(msg, "tool_calls", None),
                        exc,
                    )
                    if emit and i < attempts:
                        emit(
                            "outline_status",
                            {"phase": "retrying", "message": f"{tool_name} 结构生成异常，正在重试（{i}/{attempts - 1}）..."},
                        )
            assert last_exc is not None
            raise last_exc

        try:
            requirement_context = (
                f"原始用户需求（必须严格遵循）：\n"
                f"- 灵感：{idea}\n"
                f"- 标签：{tags}\n"
            )

            _status("generating_story", "正在生成故事设定...")
            story = await _ainvoke_section(
                self.outline_story_llm,
                (
                    "你是网络小说策划编辑。基于以下输入输出 story。\n"
                    f"{requirement_context}"
                    f"{_QUOTE_CONSTRAINT}"
                    "必须调用 submit_story，不要输出普通文本。返回 story={title, genre, volume}。"
                ),
                "submit_story",
                "story",
            )

            _status("generating_timeline", "正在生成主线大纲...")
            timeline = await _ainvoke_section(
                self.outline_timeline_llm,
                (
                    "你是网络小说策划编辑。请基于以下输入生成完整 timeline。\n"
                    f"{requirement_context}"
                    f"story：{json.dumps(story, ensure_ascii=False)}\n"
                    f"{_QUOTE_CONSTRAINT}"
                    "必须调用 submit_timeline，不要输出普通文本。"
                    "timeline 节点数量由用户需求决定，无特殊约束时按故事复杂度自行决定。"
                    "每个 summary 控制在 80 字以内。"
                    "节点按 order 递增。"
                ),
                "submit_timeline",
                "timeline",
            )

            _status("generating_character_briefs", "正在生成角色概览...")
            briefs = await _ainvoke_section(
                self.outline_character_briefs_llm,
                (
                    "你是网络小说策划编辑。请基于 story + timeline 设计所有核心角色。\n"
                    f"{requirement_context}"
                    f"story：{json.dumps(story, ensure_ascii=False)}\n"
                    f"timeline：{_compact(timeline, limit=12)}\n"
                    f"{_QUOTE_CONSTRAINT}"
                    "必须调用 submit_character_briefs，不要输出普通文本。\n"
                    "为每个角色提供 name、role_type、gender、age、first_appearance_stage、brief。\n"
                    "brief 是一句话角色定位，如'与主角共同成长的挚友'。\n"
                    "角色数量按故事需要与用户约束设置，优先列出会影响主线推进或长期出场的核心角色。"
                ),
                "submit_character_briefs",
                "briefs",
            )

            BATCH_SIZE = 4
            DETAIL_CONCURRENCY = 3
            detail_batches: list[tuple[int, list[dict]]] = []
            for batch_start in range(0, len(briefs), BATCH_SIZE):
                batch_briefs = briefs[batch_start : batch_start + BATCH_SIZE]
                batch_num = batch_start // BATCH_SIZE + 1
                detail_batches.append((batch_num, batch_briefs))

            total_batches = len(detail_batches)
            detail_semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)

            async def _generate_character_detail_batch(batch_num: int, batch_briefs: list[dict]) -> list[dict]:
                async with detail_semaphore:
                    _status("generating_character_details", f"正在生成角色详情（{batch_num}/{total_batches}）...")
                    return await _ainvoke_section(
                        self.outline_character_details_llm,
                        (
                            "你是网络小说策划编辑。请为以下角色填充详细描述。\n"
                            f"{requirement_context}"
                            f"story：{json.dumps(story, ensure_ascii=False)}\n"
                            f"timeline：{_compact(timeline, limit=12)}\n"
                            f"全部角色概览：{json.dumps(briefs, ensure_ascii=False)}\n"
                            f"本批次需要填充的角色：{json.dumps(batch_briefs, ensure_ascii=False)}\n"
                            f"{_QUOTE_CONSTRAINT}"
                            "必须调用 submit_character_details，不要输出普通文本。\n"
                            "为每个角色填充 appearance/personality/background/skills/current_status/current_goal。\n"
                            "角色字段必须是故事开始前状态。"
                        ),
                        "submit_character_details",
                        "characters",
                    )

            detail_results = await asyncio.gather(*[
                _generate_character_detail_batch(batch_num, batch_briefs)
                for batch_num, batch_briefs in detail_batches
            ])

            all_details: list[dict] = []
            for details in detail_results:
                all_details.extend(details)

            detail_map = {d["name"]: d for d in all_details}
            characters = []
            for brief in briefs:
                detail = detail_map.get(brief["name"], {})
                characters.append({
                    "name": brief["name"],
                    "role_type": brief.get("role_type", "配角"),
                    "gender": brief.get("gender", ""),
                    "age": brief.get("age", ""),
                    "appearance": detail.get("appearance", ""),
                    "personality": detail.get("personality", ""),
                    "background": detail.get("background", ""),
                    "skills": detail.get("skills", ""),
                    "current_status": detail.get("current_status", "存活"),
                    "current_goal": detail.get("current_goal", ""),
                    "first_appearance_stage": (
                        detail.get("first_appearance_stage")
                        or brief.get("first_appearance_stage", "M1")
                    ),
                })

            _status("generating_branches", "正在生成支线...")
            branches = await _ainvoke_section(
                self.outline_branches_llm,
                (
                    "你是网络小说策划编辑。请基于 story + timeline + characters 生成 branches。\n"
                    f"{requirement_context}"
                    f"story：{json.dumps(story, ensure_ascii=False)}\n"
                    f"timeline：{_compact(timeline, limit=14)}\n"
                    f"characters：{_compact(characters, limit=10)}\n"
                    f"{_QUOTE_CONSTRAINT}"
                    "必须调用 submit_branches，不要输出普通文本。attach_to 必须引用 timeline 已存在的 id，side 只能是 left/right。"
                ),
                "submit_branches",
                "branches",
            )

            _status("generating_foreshadowing", "正在生成伏笔...")
            foreshadowing = await _ainvoke_section(
                self.outline_foreshadowing_llm,
                (
                    "你是网络小说策划编辑。请基于 story + timeline + branches 生成 foreshadowing。\n"
                    f"{requirement_context}"
                    f"story：{json.dumps(story, ensure_ascii=False)}\n"
                    f"timeline：{_compact(timeline, limit=14)}\n"
                    f"branches：{_compact(branches, limit=12)}\n"
                    f"{_QUOTE_CONSTRAINT}"
                    "必须调用 submit_foreshadowing，不要输出普通文本。"
                    "foreshadowing 数量由用户需求决定，无特殊约束时按故事复杂度自行决定。"
                    "content 控制在 40 字以内。"
                    "每条伏笔需有 plant_node 和 payoff_node。"
                ),
                "submit_foreshadowing",
                "foreshadowing",
            )

            _status("generating_character_links", "正在生成角色-剧情关系...")
            character_links = await _ainvoke_section(
                self.outline_character_links_llm,
                (
                    "你是网络小说策划编辑。请基于 story/timeline/branches/foreshadowing/characters 生成 character_links。\n"
                    f"{requirement_context}"
                    f"story：{json.dumps(story, ensure_ascii=False)}\n"
                    f"timeline：{_compact(timeline, limit=14)}\n"
                    f"branches：{_compact(branches, limit=12)}\n"
                    f"foreshadowing：{_compact(foreshadowing, limit=20)}\n"
                    f"characters：{_compact(characters, limit=10)}\n"
                    f"{_QUOTE_CONSTRAINT}"
                    "必须调用 submit_character_links，不要输出普通文本。"
                    "每条记录必须包含 character_name、timeline_id、link_type。"
                    "timeline_id 必须引用已有 timeline.id。"
                    "link_type 只能是: appear, lead, conflict, ally, foreshadow_trigger, foreshadow_payoff。"
                    "character_links 数量由角色和剧情关联决定，无特殊约束时按实际关系自行生成。"
                    "summary 可为空，若填写控制在 30 字以内。"
                ),
                "submit_character_links",
                "character_links",
            )

            result = {
                "story": story,
                "timeline": timeline,
                "branches": branches,
                "foreshadowing": foreshadowing,
                "characters": characters,
                "character_links": character_links,
            }
            ctx = _outline_ctx()
            if ctx and ctx.get("work_id") and ctx.get("db"):
                work = ctx["db"].query(Work).filter_by(id=ctx["work_id"]).first()
                if work:
                    result = dict(work.outline_tree or result)
                    result["_work_id"] = work.id
            return result
        finally:
            if token is not None:
                _OUTLINE_GENERATION_CTX.reset(token)

    # DEPRECATED: 未来删除，由独立工具 generate_macro/meso/micro_outline + generate_character_details 替代
    async def _generate_three_level_outline(
        self,
        idea: str,
        tags: str,
        emit=None,
        db: Session | None = None,
        user_id: str | None = None,
        tags_list: list[str] | None = None,
    ) -> dict:
        """生成三层大纲：大纲（Macro） → 中纲（Meso） → 小纲（Micro）"""
        token = None
        if db is not None and user_id is not None:
            token = _OUTLINE_GENERATION_CTX.set({
                "db": db,
                "user_id": user_id,
                "idea": idea,
                "tags_list": tags_list or [],
            })

        def _status(phase: str, message: str):
            if emit:
                emit("outline_status", {"phase": phase, "message": message})

        def _compact(items: object, limit: int = 8) -> str:
            if isinstance(items, list):
                slim = items[:limit]
                return json.dumps(slim, ensure_ascii=False)
            if isinstance(items, dict):
                return json.dumps(items, ensure_ascii=False)
            return json.dumps(items, ensure_ascii=False)

        async def _ainvoke_section(llm, prompt_text: str, tool_name: str, field_name: str):
            attempts = 3
            last_exc: Exception | None = None
            for i in range(1, attempts + 1):
                retry_prompt = prompt_text
                if i > 1:
                    retry_prompt = (
                        f"{prompt_text}\n\n"
                        "【强约束】你上一次输出未被系统识别。"
                        "这一次只允许输出工具调用，不允许解释性文字。"
                        f"必须且只调用 {tool_name}，并确保 {field_name} 是合法 JSON。"
                    )
                try:
                    msg = await llm.ainvoke([("human", retry_prompt)])
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "outline section llm invoke failed tool=%s attempt=%s/%s err=%s",
                        tool_name, i, attempts, exc,
                    )
                    if emit and i < attempts:
                        emit(
                            "outline_status",
                            {"phase": "retrying", "message": f"{tool_name} 调用失败，正在重试（{i}/{attempts - 1}）..."},
                        )
                    continue
                try:
                    return _parse_section_from_tool_call(msg, tool_name=tool_name, field_name=field_name)
                except Exception as exc:
                    last_exc = exc
                    logger.warning(
                        "outline section tool-call parse failed tool=%s attempt=%s/%s text_preview=%r tool_calls=%r err=%s",
                        tool_name,
                        i,
                        attempts,
                        _llm_message_text(msg),
                        getattr(msg, "tool_calls", None),
                        exc,
                    )
                    if emit and i < attempts:
                        emit(
                            "outline_status",
                            {"phase": "retrying", "message": f"{tool_name} 结构生成异常，正在重试（{i}/{attempts - 1}）..."},
                        )
            assert last_exc is not None
            raise last_exc

        try:
            requirement_context = (
                f"原始用户需求（必须严格遵循）：\n"
                f"- 灵感：{idea}\n"
                f"- 标签：{tags}\n"
            )

            # ── 第一步：生成大纲（Macro Outline） ──
            _status("generating_macro_outline", "正在生成大纲（Macro Outline）...")
            macro_outline = await _ainvoke_section(
                self.outline_macro_llm,
                (
                    "你是网络小说策划编辑。请基于用户灵感生成大纲（Macro Outline）。\n"
                    f"{requirement_context}"
                    f"{_QUOTE_CONSTRAINT}"
                    "大纲包含：story（标题、类型、卷名）、macro_phases（宏观阶段数组）、core_characters（核心角色简介）、ending（结局方向，可选）。\n"
                    "macro_phases 每个阶段需包含：id、name、goal、core_setting、ending_direction（可选）、chapter_range。\n"
                    "必须调用 submit_macro_outline，不要输出普通文本。"
                ),
                "submit_macro_outline",
                "macro_outline",
            )

            # ── 第二步：生成中纲（Meso Outline） ──
            _status("generating_meso_outline", "正在生成中纲（Meso Outline）...")
            meso_outline = await _ainvoke_section(
                self.outline_meso_llm,
                (
                    "你是网络小说策划编辑。请基于大纲生成中纲（Meso Outline）。\n"
                    f"{requirement_context}"
                    f"大纲：{_compact({'story': macro_outline.get('story', {}), 'macro_phases': macro_outline.get('macro_phases', [])}, limit=20)}\n"
                    f"{_QUOTE_CONSTRAINT}"
                    "中纲包含 meso_stages 数组，每个阶段对应一个副本/地图/案件/赛事/战争/感情阶段/商业阶段。\n"
                    "每个阶段需包含：id、macro_phase_id（关联的大纲阶段ID）、name、type、cause、conflict、key_characters、twist、climax、reward、chapter_range。\n"
                    "必须调用 submit_meso_outline，不要输出普通文本。"
                ),
                "submit_meso_outline",
                "meso_outline",
            )

            # ── 第三步：生成小纲（Micro Outline） ──
            _status("generating_micro_outline", "正在生成小纲（Micro Outline）...")
            micro_outline = await _ainvoke_section(
                self.outline_micro_llm,
                (
                    "你是网络小说策划编辑。请基于中纲生成小纲（Micro Outline）。\n"
                    f"{requirement_context}"
                    f"大纲：{_compact({'story': macro_outline.get('story', {}), 'macro_phases': macro_outline.get('macro_phases', [])}, limit=10)}\n"
                    f"中纲：{_compact(meso_outline, limit=15)}\n"
                    f"{_QUOTE_CONSTRAINT}"
                    "小纲包含 micro_scenes 数组，每个场景对应章节或场景级细节。\n"
                    "每个场景需包含：id、meso_stage_id（关联的中纲阶段ID）、chapter_number、scene_number、characters、location、conflict、info_points、emotion_points、hook。\n"
                    "必须调用 submit_micro_outline，不要输出普通文本。"
                ),
                "submit_micro_outline",
                "micro_outline",
            )

            # ── 构建最终结果 ──
            # macro_outline 是整个 args dict（含 story, macro_phases, core_characters, ending）
            # meso_outline 是 meso_stages 列表
            # micro_outline 是 micro_scenes 列表
            result = {
                "story": macro_outline.get("story", {}),
                "outline": {
                    "macro_phases": macro_outline.get("macro_phases", []),
                    "core_characters": macro_outline.get("core_characters", []),
                    "ending": macro_outline.get("ending", {}),
                },
                "meso": {"meso_stages": meso_outline},
                "micro": {"micro_scenes": micro_outline},
                "characters": macro_outline.get("core_characters", []),
                "character_links": [],
            }
            ctx = _outline_ctx()
            if ctx and ctx.get("work_id") and ctx.get("db"):
                work = ctx["db"].query(Work).filter_by(id=ctx["work_id"]).first()
                if work:
                    result = dict(work.outline_tree or result)
                    result["_work_id"] = work.id
            return result
        finally:
            if token is not None:
                _OUTLINE_GENERATION_CTX.reset(token)

    @staticmethod
    def _apply_operations(outline: dict, operations: list[dict]) -> dict:
        """Apply a list of tool-call operations to an outline tree."""
        macroPhases = outline.get("outline", {}).get("macro_phases", [])
        mesoStages = outline.get("meso", {}).get("meso_stages", [])
        foreshadowing = outline.get("foreshadowing", [])
        story = outline.get("story", {})

        for op in operations:
            tool = op.get("tool", "")
            args = op.get("args", {})

            if tool == "add_timeline_node" or tool == "add_macro_phase":
                new_id = f"P{len(macroPhases) + 1}"
                order = args.get("order", len(macroPhases) + 1)
                chapter_start = int(args.get("chapter_start", args.get("chapter_range", [1, 10])[0] if isinstance(args.get("chapter_range"), list) else 1))
                chapter_end = int(args.get("chapter_end", args.get("chapter_range", [1, 10])[1] if isinstance(args.get("chapter_range"), list) else 10))
                macroPhases.append({
                    "id": new_id,
                    "order": order,
                    "name": args.get("name", args.get("development_node", "新宏观阶段")),
                    "goal": args.get("goal", args.get("summary", "")),
                    "core_setting": args.get("core_setting", ""),
                    "chapter_range": [chapter_start, chapter_end],
                })
                macroPhases.sort(key=lambda n: n.get("order", 0))

            elif tool == "add_branch_node" or tool == "add_meso_stage":
                new_id = f"M{len(mesoStages) + 1}"
                chapter_start = int(args.get("chapter_start", args.get("chapter_range", [1, 10])[0] if isinstance(args.get("chapter_range"), list) else 1))
                chapter_end = int(args.get("chapter_end", args.get("chapter_range", [1, 10])[1] if isinstance(args.get("chapter_range"), list) else 10))
                mesoStages.append({
                    "id": new_id,
                    "macro_phase_id": args.get("macro_phase_id", args.get("attach_to", macroPhases[0]["id"] if macroPhases else "P1")),
                    "type": args.get("type", args.get("side", "right")),
                    "name": args.get("name", "新中纲阶段"),
                    "cause": args.get("cause", args.get("summary", "")),
                    "conflict": args.get("conflict", ""),
                    "key_characters": args.get("key_characters", []),
                    "chapter_range": [chapter_start, chapter_end],
                })

            elif tool == "update_node":
                node_id = args.get("node_id", "")
                fields = args.get("fields", {})
                for node_list in [macroPhases, mesoStages, foreshadowing]:
                    for node in node_list:
                        if node.get("id") == node_id:
                            node.update(fields)
                            break

            elif tool == "delete_node":
                node_id = args.get("node_id", "")
                macroPhases = [n for n in macroPhases if n.get("id") != node_id]
                mesoStages = [n for n in mesoStages if n.get("id") != node_id]
                foreshadowing = [n for n in foreshadowing if n.get("id") != node_id]

            elif tool == "update_story":
                fields = args.get("fields", {})
                story.update(fields)

        outline_data = outline.get("outline", {})
        outline_data["macro_phases"] = macroPhases
        meso_data = outline.get("meso", {})
        meso_data["meso_stages"] = mesoStages

        return {
            **outline,
            "story": story,
            "outline": outline_data,
            "meso": meso_data,
            "foreshadowing": foreshadowing,
        }

    # DEPRECATED: 未来删除，用户只有 supervisor agent 对话入口
    async def generate_outline_stream(self, payload: OutlineQuickGenerateRequest, emit, *, user_id: str):
        """Stream outline generation progress via SSE, then return the final result.

        Yields SSE events:
        - outline_status
        - outline_tree_progress
        - outline_done
        - error
        """
        from app.core.database import SessionLocal
        db = SessionLocal()
        t_total = time.perf_counter()
        try:
            logger.info(
                "work.generate_outline_stream begin idea_len=%s tags_count=%s",
                len(payload.idea or ""), len(payload.tags or [])
            )
            emit("outline_status", {"phase": "generating_story", "message": "正在生成故事设定..."})
            tags_str = "、".join(payload.tags) if payload.tags else "无特殊要求"
            result_dict = await self._generate_three_level_outline(
                payload.idea.strip(),
                tags_str,
                emit=emit,
                db=db,
                user_id=user_id,
                tags_list=payload.tags,
            )
            emit("outline_status", {"phase": "parsing", "message": "正在解析并构建大纲树..."})

            work_id = result_dict.pop("_work_id", None)
            if not work_id:
                raise ValueError("大纲生成工具执行完成后未返回 work_id")
            outline_tree = OutlineTreeData.model_validate(result_dict)
            outline_data = outline_tree.model_dump(mode="json")
            story = outline_data["story"]
            logger.info(
                "work.generate_outline_stream validate_done macro_phases=%s meso_stages=%s foreshadowing=%s characters=%s character_links=%s",
                len(outline_data.get("outline", {}).get("macro_phases", [])),
                len(outline_data.get("meso", {}).get("meso_stages", [])),
                len(outline_data.get("foreshadowing", [])),
                len(outline_data.get("characters", [])),
                len(outline_data.get("character_links", [])),
            )

            emit("outline_tree_progress", {
                "section": "story",
                "index": 1,
                "total": 1,
                "node": story,
            })
            for i, node in enumerate(outline_data.get("outline", {}).get("macro_phases", []), start=1):
                emit("outline_tree_progress", {
                    "section": "macro_phases",
                    "index": i,
                    "total": len(outline_data.get("outline", {}).get("macro_phases", [])),
                    "node": node,
                })
            for i, node in enumerate(outline_data.get("meso", {}).get("meso_stages", []), start=1):
                emit("outline_tree_progress", {
                    "section": "meso_stages",
                    "index": i,
                    "total": len(outline_data.get("meso", {}).get("meso_stages", [])),
                    "node": node,
                })
            for i, node in enumerate(outline_data.get("foreshadowing", []), start=1):
                emit("outline_tree_progress", {
                    "section": "foreshadowing",
                    "index": i,
                    "total": len(outline_data.get("foreshadowing", [])),
                    "node": node,
                })
            for i, node in enumerate(outline_data.get("characters", []), start=1):
                emit("outline_tree_progress", {
                    "section": "characters",
                    "index": i,
                    "total": len(outline_data.get("characters", [])),
                    "node": node,
                })
            t_db = time.perf_counter()
            characters_data = outline_data.get("characters", [])
            logger.info(
                "work.generate_outline_stream db_done elapsed_ms=%.1f work_id=%s chars=%s",
                (time.perf_counter() - t_db) * 1000,
                work_id,
                len(characters_data),
            )

            emit("outline_done", {
                "work_id": work_id,
                "title": story["title"],
                "outline_tree": outline_data,
            })
            logger.info(
                "work.generate_outline_stream done total_ms=%.1f work_id=%s",
                (time.perf_counter() - t_total) * 1000,
                work_id,
            )
        except Exception as exc:
            logger.exception("outline streaming failed")
            emit("error", {"message": str(exc)})
        finally:
            db.close()

    def update_outline(self, work_id: str, outline_tree: dict, db: Session, *, user_id: str) -> WorkOut:
        """Directly save an outline tree (from user inline editing)."""
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        story = outline_tree.get("story", {})
        work.outline_tree = outline_tree
        work.title = story.get("title", work.title)
        work.genre = story.get("genre", work.genre)
        db.commit()
        db.refresh(work)
        return WorkOut.model_validate(work)

    @staticmethod
    def update_requirements_doc(
        work_id: str,
        content: str,
        db: Session,
        *,
        user_id: str,
    ) -> dict[str, str]:
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        work.requirements_doc = content
        db.commit()
        db.refresh(work)
        return {"content": work.requirements_doc or ""}

    @staticmethod
    def update_meso_doc(
        work_id: str,
        content: str,
        db: Session,
        *,
        user_id: str,
    ) -> dict[str, str]:
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        work.meso_doc = content
        db.commit()
        db.refresh(work)
        return {"content": work.meso_doc or ""}

    @staticmethod
    def update_micro_doc(
        work_id: str,
        content: str,
        db: Session,
        *,
        user_id: str,
    ) -> dict[str, str]:
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        work.micro_doc = content
        db.commit()
        db.refresh(work)
        return {"content": work.micro_doc or ""}

    async def chat_edit_async(
        self, work_id: str, user_message: str, history: list[dict], db: Session,
        session_id: str | None = None,
        dry_run: bool = False,
        max_iterations: int = 10,
        *, user_id: str,
    ) -> ChatEditResponse:
        """Async outline chat edit using Tool-Calling loop.

        Replaces the old JSON output approach (with_structured_output) with native
        LLM tool-calling, eliminating field name inconsistencies (e.g. 'name' vs 'tool').

        Args:
            dry_run: 如果为 True，工具正常执行但最后不 commit。
                     调用方负责在确认后 commit 或 rollback。
            max_iterations: Tool-Calling 最大轮次。传 1 可强制单次 LLM 交互。
        """
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        from app.services.outline_tools import ALL_OUTLINE_TOOLS

        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        from app.services.session_service import create_session, touch_session, get_session
        if session_id:
            existing = get_session(db, session_id)
            if not existing:
                session_id = None
        if not session_id:
            session_id = new_session_id()

        chat_s = get_session(db, session_id)
        if not chat_s:
            create_session(
                db, work_id=work_id, session_id=session_id,
            )
        else:
            touch_session(db, session_id)

        log_event(db, work_id=work_id, session_id=session_id,
                  session_type="outline_chat", role="user", content=user_message)

        current_outline = json.dumps(work.outline_tree, ensure_ascii=False, indent=2)
        history_str = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history
        ) if history else "（无）"

        from app.models.work_model import Character
        characters = db.query(Character).filter_by(work_id=work_id).order_by(Character.first_appearance_stage).all()
        characters_info = self._format_characters_for_prompt(characters)

        # Build system prompt
        template = self._read_prompt("outline_system.txt")
        system_text = template.format(
            current_outline=current_outline,
            characters_info=characters_info,
            history=history_str,
            user_message=user_message.strip(),
        )

        # Prepare mutable outline_tree for tools to modify in-place
        outline_tree = work.outline_tree
        tools_map = {t.name: t for t in ALL_OUTLINE_TOOLS}
        tool_config = {
            "configurable": {
                "outline_tree": outline_tree,
                "db": db,
                "work_id": work_id,
            },
        }

        # Build message list
        messages = [
            SystemMessage(content=system_text),
            HumanMessage(content=user_message.strip()),
        ]

        # LLM bound with tools
        llm_with_tools = self.chat_model.bind_tools(ALL_OUTLINE_TOOLS)

        all_operations = []
        loop_max = max(1, int(max_iterations or 1))

        try:
            for _ in range(loop_max):
                ai_msg = await llm_with_tools.ainvoke(messages)
                messages.append(ai_msg)

                # No tool_calls → LLM is done, extract text response
                if not ai_msg.tool_calls:
                    break

                # Execute each tool_call sequentially (outline_tree is shared mutable state)
                for tc in ai_msg.tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    tool_call_id = tc["id"]

                    # Record operation for response
                    all_operations.append({
                        "tool": tool_name,
                        "args": tool_args,
                    })

                    # Execute the tool
                    tool_fn = tools_map.get(tool_name)
                    if tool_fn:
                        try:
                            result = tool_fn.invoke(tool_args, config=tool_config)
                            tool_response = str(result)
                        except Exception as tool_exc:
                            tool_response = f"工具执行错误: {tool_exc}"
                            logger.warning("Tool %s execution error: %s", tool_name, tool_exc)
                    else:
                        tool_response = f"未知工具: {tool_name}"

                    messages.append(
                        ToolMessage(content=tool_response, tool_call_id=tool_call_id)
                    )

            # Extract assistant message from the last AI response
            assistant_message = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    assistant_message = msg.content
                    break
            if not assistant_message:
                assistant_message = "已完成修改。" if all_operations else "请告诉我你想修改什么？"

            # Save updated outline (tools modified it in-place via config)
            from sqlalchemy.orm.attributes import flag_modified

            updated_outline = tool_config["configurable"]["outline_tree"]
            story = updated_outline.get("story", {})
            work.outline_tree = updated_outline
            flag_modified(work, "outline_tree")
            work.title = story.get("title", work.title)
            work.genre = story.get("genre", work.genre)

            if dry_run:
                # dry_run 模式：flush 到数据库事务中但不 commit，
                # 调用方负责在用户确认后 commit 或 rollback
                db.flush()
            else:
                db.commit()

                log_event(db, work_id=work_id, session_id=session_id,
                          session_type="outline_chat", role="assistant",
                          content=assistant_message,
                          meta={"operations": all_operations})

            return ChatEditResponse(
                assistant_message=assistant_message,
                operations=all_operations,
                outline_tree=updated_outline,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM chat edit failed: {exc}"
            ) from exc

    @staticmethod
    def _format_characters_for_prompt(characters) -> str:
        """Format characters list into a readable string for the prompt."""
        if not characters:
            return "（暂无角色）"
        lines = []
        for c in characters:
            parts = [f"**{c.name}**（{c.role_type}）"]
            if c.gender:
                parts.append(f"  性别：{c.gender}")
            if c.age:
                parts.append(f"  年龄：{c.age}")
            if c.appearance:
                parts.append(f"  外貌：{c.appearance}")
            if c.personality:
                parts.append(f"  性格：{c.personality}")
            if c.background:
                parts.append(f"  背景：{c.background}")
            if c.skills:
                parts.append(f"  能力：{c.skills}")
            if c.current_status:
                parts.append(f"  状态：{c.current_status}")
            if c.current_goal:
                parts.append(f"  目的：{c.current_goal}")
            if c.last_location:
                parts.append(f"  位置：{c.last_location}")
            if c.notes:
                parts.append(f"  备注：{c.notes}")
            lines.append("\n".join(parts))
        return "\n\n".join(lines)

    @staticmethod
    def _apply_character_operations(work_id: str, operations: list[dict], db: Session):
        """Apply character-related operations from LLM output."""
        from app.models.work_model import Character

        for op in operations:
            tool = op.get("tool", "")
            args = op.get("args", {})

            if tool == "update_character":
                name = args.get("name", "")
                fields = args.get("fields", {})
                char = db.query(Character).filter_by(work_id=work_id, name=name).first()
                if char and fields:
                    for k, v in fields.items():
                        if hasattr(char, k) and k not in ("id", "work_id", "created_at", "updated_at"):
                            setattr(char, k, v)

            elif tool == "add_character":
                name = args.get("name", "")
                if name:
                    existing = db.query(Character).filter_by(work_id=work_id, name=name).first()
                    if not existing:
                        char = Character(
                            work_id=work_id,
                            name=name,
                            role_type=args.get("role_type", "配角"),
                            gender=args.get("gender", ""),
                            age=args.get("age", ""),
                            appearance=args.get("appearance", ""),
                            personality=args.get("personality", ""),
                            background=args.get("background", ""),
                            skills=args.get("skills", ""),
                            current_status=args.get("current_status", "存活"),
                            current_goal=args.get("current_goal", ""),
                            first_appearance_stage=str(args.get("first_appearance_stage", "M1")),
                            notes=args.get("notes", ""),
                        )
                        db.add(char)

            elif tool == "delete_character":
                name = args.get("name", "")
                if name:
                    char = db.query(Character).filter_by(work_id=work_id, name=name).first()
                    if char:
                        db.delete(char)

    @staticmethod
    def _find_chapter_outline(outline_tree: dict, chapter_number: int) -> str:
        """Extract the outline info relevant to a specific chapter number."""
        macro_phases = outline_tree.get("outline", {}).get("macro_phases", [])
        meso_stages = outline_tree.get("meso", {}).get("meso_stages", [])
        micro_scenes = outline_tree.get("micro", {}).get("micro_scenes", [])

        relevant = []
        for phase in macro_phases:
            cr = phase.get("chapter_range", [0, 0])
            if cr[0] <= chapter_number <= cr[1]:
                relevant.append(f"[大纲] {phase.get('name', '')}：{phase.get('goal', '')}（第{cr[0]}-{cr[1]}章）")
        for stage in meso_stages:
            cr = stage.get("chapter_range", [0, 0])
            if cr[0] <= chapter_number <= cr[1]:
                relevant.append(
                    f"[中纲·{stage.get('name', '')}] "
                    f"起因：{stage.get('cause', '')}，冲突：{stage.get('conflict', '')}，"
                    f"关键人物：{'、'.join(stage.get('key_characters', []))}（第{cr[0]}-{cr[1]}章）"
                )
        for scene in micro_scenes:
            if scene.get("chapter_number") == chapter_number:
                relevant.append(
                    f"[小纲·第{scene.get('chapter_number', '')}章场景{scene.get('scene_number', '')}] "
                    f"人物：{'、'.join(scene.get('characters', []))}，地点：{scene.get('location', '')}，"
                    f"冲突：{scene.get('conflict', '')}，钩子：{scene.get('hook', '')}"
                )

        return "\n".join(relevant) if relevant else "（无匹配纲要，请根据整体大纲自行推进）"

    @staticmethod
    def list_chapters(work_id: str, db: Session, *, user_id: str) -> list[ChapterOut]:
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        chapters = (
            db.query(Chapter)
            .filter_by(work_id=work_id)
            .order_by(Chapter.chapter_number)
            .all()
        )
        return [ChapterOut.model_validate(c) for c in chapters]

    @staticmethod
    def update_chapter(work_id: str, chapter_number: int, payload: ChapterUpdateRequest, db: Session, *, user_id: str) -> ChapterOut:
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        old_title = chapter.title
        if payload.title is not None:
            chapter.title = payload.title
        if payload.content is not None:
            chapter.content = payload.content
            chapter.status = "已保存"
        db.commit()
        db.refresh(chapter)
        logger.info(
            "chapter_update_saved work_id=%s chapter=%s old_title=%r new_title=%r title_in_payload=%s",
            work_id,
            chapter_number,
            old_title,
            chapter.title,
            payload.title is not None,
        )
        return ChapterOut.model_validate(chapter)

    @staticmethod
    def delete_last_chapter(work_id: str, db: Session, *, user_id: str) -> ChapterDeleteLastResponse:
        from app.models.agent_model import AgentState
        from app.models.work_model import AgentLog

        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        last_chapter = (
            db.query(Chapter)
            .filter_by(work_id=work_id)
            .order_by(Chapter.chapter_number.desc())
            .first()
        )
        if not last_chapter:
            raise HTTPException(status_code=400, detail="当前没有可删除的章节")

        deleted_number = int(last_chapter.chapter_number)

        # 清理与该章节号绑定的衍生数据，避免残留脏数据影响后续展示/编辑。
        db.query(ChapterMetadata).filter_by(
            work_id=work_id,
            chapter_number=deleted_number,
        ).delete(synchronize_session=False)
        db.query(AgentState).filter_by(
            work_id=work_id,
            chapter_number=deleted_number,
        ).delete(synchronize_session=False)
        db.query(AgentLog).filter_by(
            work_id=work_id,
            chapter_number=deleted_number,
        ).delete(synchronize_session=False)

        db.delete(last_chapter)
        db.commit()

        return ChapterDeleteLastResponse(
            deleted_chapter_number=deleted_number,
            next_chapter_number=deleted_number,
        )

    @staticmethod
    def get_chapter_intel(work_id: str, chapter_number: int, db: Session, *, user_id: str) -> ChapterIntelOut:
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")

        metadata = (
            db.query(ChapterMetadata)
            .filter_by(work_id=work_id, chapter_number=chapter_number)
            .first()
        )

        if not metadata:
            return ChapterIntelOut(
                work_id=work_id,
                chapter_number=chapter_number,
                summary="",
                key_plot_points=[],
                outline_links=[],
                involved_characters=[],
                facts=[],
                updated_at=None,
                chapter_updated_at=chapter.updated_at,
            )

        return ChapterIntelOut(
            work_id=work_id,
            chapter_number=chapter_number,
            summary=metadata.summary or "",
            key_plot_points=list(metadata.key_plot_points or []),
            outline_links=list(metadata.outline_links or []),
            involved_characters=list(metadata.involved_characters or []),
            facts=list(metadata.facts or []),
            updated_at=metadata.updated_at,
            chapter_updated_at=chapter.updated_at,
        )

    @staticmethod
    def list_works(user_id: str, db: Session) -> list[WorkOut]:
        works = (
            db.query(Work)
            .filter_by(user_id=user_id)
            .order_by(Work.created_at.desc())
            .all()
        )
        return [WorkOut.model_validate(w) for w in works]

    @staticmethod
    def get_work(work_id: str, user_id: str, db: Session) -> WorkOut:
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        # Self-heal historical inconsistency: characters table vs outline_tree.characters
        chars = (
            db.query(Character)
            .filter_by(work_id=work_id)
            .order_by(Character.first_appearance_stage.asc(), Character.created_at.asc())
            .all()
        )
        outline = work.outline_tree or {}
        outline_chars = [
            {
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
                "first_appearance_stage": c.first_appearance_stage or "M1",
            }
            for c in chars
        ]
        if outline.get("characters") != outline_chars:
            outline["characters"] = outline_chars
            work.outline_tree = outline
            flag_modified(work, "outline_tree")
            db.commit()
            db.refresh(work)
        return WorkOut.model_validate(work)

    @staticmethod
    def delete_work(work_id: str, user_id: str, db: Session) -> None:
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        db.delete(work)
        db.commit()
