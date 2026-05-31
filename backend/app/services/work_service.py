import json
import logging
import time
import asyncio
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from langchain_core.prompts import PromptTemplate
from langchain_core.tools import StructuredTool
from app.core.deepseek_llm import DeepSeekChatOpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.models.work_model import Chapter, ChapterMetadata, Character, Work
from app.services.agent_log_service import log_event, new_session_id
from app.schemas.work_schema import (
    BranchNode,
    ChapterChatResponse,
    ChapterGenerateResponse,
    ChapterDeleteLastResponse,
    ChapterIntelOut,
    ChapterOut,
    ChapterUpdateRequest,
    ChatEditResponse,
    CharacterBrief,
    CharacterDetail,
    ForeshadowingNode,
    OutlineGenerateResponse,
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
        "timeline": [],
        "branches": [],
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
            "first_chapter": char_data.get("first_chapter", 1),
            "last_chapter": char_data.get("first_chapter"),
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
            "first_chapter": brief.get("first_chapter", 1),
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
    description="提交角色骨架列表：所有角色的 name/role_type/gender/age/first_chapter/brief。",
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
        if field_name not in args:
            raise ValueError(f"{tool_name} missing field: {field_name}")
        handler = submit_handlers.get(tool_name)
        if handler:
            handler(**args)
        return args[field_name]

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
        # NOTE: chat_edit_model (with_structured_output) removed — chat_edit / chat_edit_async
        # now use native Tool-Calling via self.chat_model.bind_tools(ALL_OUTLINE_TOOLS).
        # chapter_chat_model kept for backward compatibility with deprecated chapter_chat_edit API.
        self.chapter_chat_model = base_model.with_structured_output(ChapterChatResponse, strict=True)

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
                    "为每个角色提供 name、role_type、gender、age、first_chapter、brief。\n"
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
                    "first_chapter": brief.get("first_chapter", 1),
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

    @staticmethod
    def _apply_operations(outline: dict, operations: list[dict]) -> dict:
        """Apply a list of tool-call operations to an outline tree."""
        timeline = outline.get("timeline", [])
        branches = outline.get("branches", [])
        foreshadowing = outline.get("foreshadowing", [])
        story = outline.get("story", {})

        for op in operations:
            tool = op.get("tool", "")
            args = op.get("args", {})

            if tool == "add_timeline_node":
                new_id = f"N{len(timeline) + 1}"
                order = args.get("order", len(timeline) + 1)
                timeline.append({
                    "id": new_id,
                    "order": order,
                    "development_node": args.get("development_node", "新主线节点"),
                    "summary": args.get("summary", ""),
                    "time_node": args.get("time_node", f"阶段{len(timeline) + 1}"),
                    "chapter_start": int(args.get("chapter_start", 1)),
                    "chapter_end": int(args.get("chapter_end", 10)),
                })
                # Re-sort by order
                timeline.sort(key=lambda n: n.get("order", 0))

            elif tool == "add_branch_node":
                new_id = f"B{len(branches) + 1}"
                branches.append({
                    "id": new_id,
                    "attach_to": args.get("attach_to", timeline[0]["id"] if timeline else "N1"),
                    "side": args.get("side", "right"),
                    "name": args.get("name", "新支线"),
                    "summary": args.get("summary", ""),
                    "chapter_start": int(args.get("chapter_start", 1)),
                    "chapter_end": int(args.get("chapter_end", 10)),
                })

            elif tool == "update_node":
                node_id = args.get("node_id", "")
                fields = args.get("fields", {})
                # Search in timeline, branches, foreshadowing
                for node_list in [timeline, branches, foreshadowing]:
                    for node in node_list:
                        if node.get("id") == node_id:
                            node.update(fields)
                            break

            elif tool == "delete_node":
                node_id = args.get("node_id", "")
                timeline = [n for n in timeline if n.get("id") != node_id]
                branches = [n for n in branches if n.get("id") != node_id]
                foreshadowing = [n for n in foreshadowing if n.get("id") != node_id]

            elif tool == "update_story":
                fields = args.get("fields", {})
                story.update(fields)

        return {
            **outline,
            "story": story,
            "timeline": timeline,
            "branches": branches,
            "foreshadowing": foreshadowing,
        }

    def generate_outline(
        self, payload: OutlineQuickGenerateRequest, db: Session, *, user_id: str
    ) -> OutlineGenerateResponse:
        try:
            tags_str = "、".join(payload.tags) if payload.tags else "无特殊要求"
            result_dict = asyncio.run(
                self._generate_outline_sections(
                    payload.idea.strip(),
                    tags_str,
                    db=db,
                    user_id=user_id,
                    tags_list=payload.tags,
                )
            )
            work_id = result_dict.pop("_work_id", None)
            outline_tree = OutlineTreeData.model_validate(result_dict)
            if not work_id:
                raise ValueError("大纲生成工具执行完成后未返回 work_id")

            return OutlineGenerateResponse(outline_tree=outline_tree, work_id=work_id)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM outline generation failed: {exc}"
            ) from exc

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
            result_dict = await self._generate_outline_sections(
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
                "work.generate_outline_stream validate_done timeline=%s branches=%s foreshadowing=%s characters=%s character_links=%s",
                len(outline_data.get("timeline", [])),
                len(outline_data.get("branches", [])),
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
            for i, node in enumerate(outline_data.get("timeline", []), start=1):
                emit("outline_tree_progress", {
                    "section": "timeline",
                    "index": i,
                    "total": len(outline_data.get("timeline", [])),
                    "node": node,
                })
            for i, node in enumerate(outline_data.get("branches", []), start=1):
                emit("outline_tree_progress", {
                    "section": "branches",
                    "index": i,
                    "total": len(outline_data.get("branches", [])),
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

    def chat_edit(
        self, work_id: str, user_message: str, history: list[dict], db: Session,
        session_id: str | None = None, *, user_id: str,
    ) -> ChatEditResponse:
        """Synchronous outline chat edit using Tool-Calling loop."""
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

        # Ensure a session record exists
        chat_s = get_session(db, session_id)
        if not chat_s:
            create_session(
                db, work_id=work_id, session_id=session_id,
            )
        else:
            touch_session(db, session_id)

        # Log user message
        log_event(db, work_id=work_id, session_id=session_id,
                  session_type="outline_chat", role="user", content=user_message)

        current_outline = json.dumps(work.outline_tree, ensure_ascii=False, indent=2)
        history_str = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history
        ) if history else "（无）"

        # Build characters context
        from app.models.work_model import Character
        characters = db.query(Character).filter_by(work_id=work_id).order_by(Character.first_chapter).all()
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
        max_iterations = 10

        try:
            for _ in range(max_iterations):
                ai_msg = llm_with_tools.invoke(messages)
                messages.append(ai_msg)

                # No tool_calls → LLM is done
                if not ai_msg.tool_calls:
                    break

                # Execute each tool_call sequentially
                for tc in ai_msg.tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    tool_call_id = tc["id"]

                    all_operations.append({
                        "tool": tool_name,
                        "args": tool_args,
                    })

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

            # Extract assistant message
            assistant_message = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    assistant_message = msg.content
                    break
            if not assistant_message:
                assistant_message = "已完成修改。" if all_operations else "请告诉我你想修改什么？"

            # Save updated outline
            from sqlalchemy.orm.attributes import flag_modified

            updated_outline = tool_config["configurable"]["outline_tree"]
            story = updated_outline.get("story", {})
            work.outline_tree = updated_outline
            flag_modified(work, "outline_tree")
            work.title = story.get("title", work.title)
            work.genre = story.get("genre", work.genre)
            db.commit()

            # Log assistant response
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
        characters = db.query(Character).filter_by(work_id=work_id).order_by(Character.first_chapter).all()
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
                            first_chapter=int(args.get("first_chapter", 1)),
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
        timeline = outline_tree.get("timeline", [])
        branches = outline_tree.get("branches", [])

        relevant = []
        for node in timeline:
            if node.get("chapter_start", 0) <= chapter_number <= node.get("chapter_end", 0):
                summary = node.get("summary") or (node.get("mainline") if isinstance(node.get("mainline"), str) else "")
                relevant.append(f"[主线] {node.get('time_node', '')}：{node.get('development_node', '')}。{summary}（第{node['chapter_start']}-{node['chapter_end']}章）")
        for node in branches:
            if node.get("chapter_start", 0) <= chapter_number <= node.get("chapter_end", 0):
                relevant.append(f"[支线·{node.get('name', '')}] {node.get('summary', '')}（第{node['chapter_start']}-{node['chapter_end']}章）")

        return "\n".join(relevant) if relevant else "（无匹配纲要，请根据整体大纲自行推进）"

    def generate_chapter(self, work_id: str, chapter_number: int, db: Session, *, user_id: str) -> ChapterGenerateResponse:
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        outline_tree = work.outline_tree

        # Collect previous chapters' content (up to 3 most recent before this one)
        prev_chapters = (
            db.query(Chapter)
            .filter_by(work_id=work_id)
            .filter(Chapter.chapter_number < chapter_number)
            .filter(Chapter.content != "")
            .order_by(Chapter.chapter_number.desc())
            .limit(3)
            .all()
        )
        prev_chapters.reverse()

        previous_text = ""
        if prev_chapters:
            parts = []
            for ch in prev_chapters:
                summary = ch.content
                parts.append(f"--- 第{ch.chapter_number}章 {ch.title} ---\n{summary}")
            previous_text = "\n\n".join(parts)
        else:
            previous_text = "（这是第一章，暂无前文）"

        story_info = json.dumps(outline_tree.get("story", {}), ensure_ascii=False)
        outline_text = json.dumps(outline_tree, ensure_ascii=False, indent=2)
        chapter_outline = self._find_chapter_outline(outline_tree, chapter_number)

        template = self._read_prompt("work_generate_chapter.txt")
        prompt = PromptTemplate.from_template(template)

        chain = prompt | self.chat_model
        try:
            result = chain.invoke({
                "story_info": story_info,
                "outline_tree": outline_text,
                "chapter_number": str(chapter_number),
                "chapter_outline": chapter_outline,
                "previous_chapters": previous_text,
            })

            content = result.content if hasattr(result, "content") else str(result)

            # Extract title from first line if it matches "第X章 ..." pattern
            lines = content.strip().split("\n", 1)
            title = ""
            body = content.strip()
            if lines and lines[0].startswith("第") and "章" in lines[0][:10]:
                title = lines[0].strip()
                body = lines[1].strip() if len(lines) > 1 else ""

            # Upsert: update if exists, create if not
            chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
            if chapter:
                chapter.title = title or chapter.title
                chapter.content = body
                chapter.status = "已保存"
            else:
                chapter = Chapter(
                    work_id=work_id,
                    chapter_number=chapter_number,
                    title=title or f"第{chapter_number}章",
                    content=body,
                    status="已保存",
                )
                db.add(chapter)

            db.commit()
            db.refresh(chapter)
            return ChapterGenerateResponse(chapter=ChapterOut.model_validate(chapter))
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM chapter generation failed: {exc}"
            ) from exc

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
    def get_chapter(work_id: str, chapter_number: int, db: Session, *, user_id: str) -> ChapterOut:
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        return ChapterOut.model_validate(chapter)

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
                foreshadows=[],
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
            foreshadows=list(metadata.foreshadows or []),
            facts=list(metadata.facts or []),
            updated_at=metadata.updated_at,
            chapter_updated_at=chapter.updated_at,
        )

    # DEPRECATED: chapter_chat_edit is no longer actively called by the frontend.
    # The SupervisorAgent's edit_chapter tool uses EditChapterAgent instead.
    # This method is retained for API backward compatibility.
    def chapter_chat_edit(
        self,
        work_id: str,
        chapter_number: int,
        user_message: str,
        history: list[dict],
        db: Session,
        *, user_id: str,
    ) -> ChapterChatResponse:
        """Use LLM to edit chapter content via conversation (DEPRECATED — use edit_chapter via SupervisorAgent)."""
        work = db.query(Work).filter_by(id=work_id, user_id=user_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        session_id = new_session_id()

        # Log user message
        log_event(db, work_id=work_id, session_id=session_id,
                  session_type="chapter_chat", role="user",
                  content=user_message, chapter_number=chapter_number)

        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        current_content = chapter.content if chapter else ""
        current_title = chapter.title if chapter else ""

        outline_tree = work.outline_tree
        story_info = json.dumps(outline_tree.get("story", {}), ensure_ascii=False)
        outline_text = json.dumps(outline_tree, ensure_ascii=False, indent=2)
        chapter_outline = self._find_chapter_outline(outline_tree, chapter_number)

        history_str = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history
        ) if history else "（无）"

        template = self._read_prompt("work_chapter_chat_edit.txt")
        prompt = PromptTemplate.from_template(template)

        chain = prompt | self.chapter_chat_model
        try:
            result = chain.invoke({
                "story_info": story_info,
                "outline_tree": outline_text,
                "chapter_number": str(chapter_number),
                "chapter_outline": chapter_outline,
                "current_content": current_content or "（尚未生成正文）",
                "history": history_str,
                "user_message": user_message.strip(),
            })

            # result is already ChapterChatResponse instance
            result_dict = result.model_dump() if hasattr(result, "model_dump") else dict(result)
            assistant_message = result_dict.get("assistant_message", "已完成修改。")
            proposed_content = result_dict.get("proposed_content", current_content)
            proposed_title = result_dict.get("proposed_title")

            # Log assistant response
            log_event(db, work_id=work_id, session_id=session_id,
                      session_type="chapter_chat", role="assistant",
                      content=assistant_message, chapter_number=chapter_number,
                      meta={"proposed_title": proposed_title,
                            "proposed_content_preview": (proposed_content or "")})

            return ChapterChatResponse(
                assistant_message=assistant_message,
                proposed_content=proposed_content,
                proposed_title=proposed_title if proposed_title else None,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log_event(db, work_id=work_id, session_id=session_id,
                      session_type="chapter_chat", role="system",
                      content=f"错误：{exc}", chapter_number=chapter_number)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM chapter chat edit failed: {exc}"
            ) from exc

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
            .order_by(Character.first_chapter.asc(), Character.created_at.asc())
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
                "first_chapter": c.first_chapter or 1,
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
