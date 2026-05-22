import json
import logging
import time
import asyncio
from pathlib import Path

from fastapi import HTTPException, status
from langchain_core.prompts import PromptTemplate
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.models.work_model import Chapter, ChapterMetadata, Character, User, Work
from app.services.agent_log_service import log_event, new_session_id
from app.schemas.work_schema import (
    BranchNode,
    ChapterChatResponse,
    ChapterGenerateResponse,
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

# Hardcoded demo user until auth is implemented
DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"


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


def _ensure_demo_user(db: Session) -> None:
    if not db.query(User).filter_by(id=DEMO_USER_ID).first():
        db.add(User(
            id=DEMO_USER_ID,
            username="创作者",
            email="demo@novel.local",
            password_hash="no-login",
        ))
        db.commit()


# DEPRECATED: _ChatEditOutput is no longer used by chat_edit / chat_edit_async.
# These methods now use native Tool-Calling; operations are collected from AIMessage.tool_calls.
class _ChatEditOutput(BaseModel):
    assistant_message: str
    operations: list[dict]


class _SubmitOutlineInput(OutlineTreeData):
    """Tool-call payload for initial outline generation."""


def _submit_outline_tool(**kwargs) -> str:
    """Accept the complete generated outline as structured tool arguments."""
    return "outline_received"


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
    return "story_received"


def _submit_timeline_tool(**kwargs) -> str:
    return "timeline_received"


def _submit_character_briefs_tool(**kwargs) -> str:
    return "character_briefs_received"


def _submit_character_details_tool(**kwargs) -> str:
    return "character_details_received"


def _submit_branches_tool(**kwargs) -> str:
    return "branches_received"


def _submit_foreshadowing_tool(**kwargs) -> str:
    return "foreshadowing_received"


def _submit_character_links_tool(**kwargs) -> str:
    return "character_links_received"


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
        return args
    raise ValueError("LLM did not call submit_outline")


def _extract_tool_calls(ai_msg) -> list[dict]:
    """Return tool calls exposed on AIMessage.tool_calls only."""
    return list(getattr(ai_msg, "tool_calls", None) or [])


def _parse_section_from_tool_call(ai_msg, *, tool_name: str, field_name: str):
    tool_calls = _extract_tool_calls(ai_msg)
    for call in tool_calls:
        if call.get("name") != tool_name:
            continue
        args = call.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError(f"{tool_name} tool args must be an object")
        if field_name not in args:
            raise ValueError(f"{tool_name} missing field: {field_name}")
        return args[field_name]

    raise ValueError(f"LLM did not call {tool_name}")


class WorkService:
    def __init__(self) -> None:
        model_conf = settings.get_model_config()
        base_model = ChatOpenAI(
            model=settings.default_model,
            api_key=model_conf["api_key"],
            base_url=model_conf["base_url"],
            temperature=0.7,
            request_timeout=(15, 180),
            max_retries=0,
        )
        self.chat_model = base_model

        # 大纲生成使用 pro 模型（强制 tool_choice 场景需要更强的模型）
        outline_model_name = "deepseek-v4-flash"  # deepseek-v4-pro 模型
        outline_conf = settings.get_model_config(outline_model_name)
        outline_model = ChatOpenAI(
            model=outline_model_name,
            api_key=outline_conf["api_key"],
            base_url=outline_conf["base_url"],
            temperature=0.7,
            request_timeout=(15, 180),
            max_retries=0,
        )

        self.outline_tool_llm = outline_model.bind_tools(
            [SUBMIT_OUTLINE_TOOL],
            tool_choice="submit_outline",
            max_tokens=393216,
            extra_body={"enable_thinking": False},
        )
        self.outline_story_llm = outline_model.bind_tools(
            [SUBMIT_STORY_TOOL],
            tool_choice="submit_story",
            max_tokens=393216,
            extra_body={"enable_thinking": False},
        )
        self.outline_timeline_llm = outline_model.bind_tools(
            [SUBMIT_TIMELINE_TOOL],
            tool_choice="submit_timeline",
            max_tokens=393216,
            extra_body={"enable_thinking": False},
        )
        self.outline_character_briefs_llm = outline_model.bind_tools(
            [SUBMIT_CHARACTER_BRIEFS_TOOL],
            tool_choice="submit_character_briefs",
            max_tokens=393216,
            extra_body={"enable_thinking": False},
        )
        self.outline_character_details_llm = outline_model.bind_tools(
            [SUBMIT_CHARACTER_DETAILS_TOOL],
            tool_choice="submit_character_details",
            max_tokens=393216,
            extra_body={"enable_thinking": False},
        )
        self.outline_branches_llm = outline_model.bind_tools(
            [SUBMIT_BRANCHES_TOOL],
            tool_choice="submit_branches",
            max_tokens=393216,
            extra_body={"enable_thinking": False},
        )
        self.outline_foreshadowing_llm = outline_model.bind_tools(
            [SUBMIT_FORESHADOWING_TOOL],
            tool_choice="submit_foreshadowing",
            max_tokens=393216,
            extra_body={"enable_thinking": False},
        )
        self.outline_character_links_llm = outline_model.bind_tools(
            [SUBMIT_CHARACTER_LINKS_TOOL],
            tool_choice="submit_character_links",
            max_tokens=393216,
            extra_body={"enable_thinking": False},
        )
        # NOTE: chat_edit_model (with_structured_output) removed — chat_edit / chat_edit_async
        # now use native Tool-Calling via self.chat_model.bind_tools(ALL_OUTLINE_TOOLS).
        # chapter_chat_model kept for backward compatibility with deprecated chapter_chat_edit API.
        self.chapter_chat_model = base_model.with_structured_output(ChapterChatResponse, strict=True)

    def _read_prompt(self, file_name: str) -> str:
        path = PROMPT_DIR / file_name
        return path.read_text(encoding="utf-8")

    async def _generate_outline_sections(self, idea: str, tags: str, emit=None) -> dict:
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
                        _llm_message_text(msg)[:500],
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
                "必须调用 submit_timeline，不要输出普通文本。"
                "timeline 节点数量控制在 6-10。"
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
                "必须调用 submit_character_briefs，不要输出普通文本。\n"
                "为每个角色提供 name、role_type、gender、age、first_chapter、brief。\n"
                "brief 是一句话角色定位，如'与主角共同成长的挚友'。\n"
                "角色数量控制在 8-15 个，必须包含主角和主要反派。"
            ),
            "submit_character_briefs",
            "briefs",
        )

        BATCH_SIZE = 4
        all_details: list[dict] = []

        for batch_start in range(0, len(briefs), BATCH_SIZE):
            batch_briefs = briefs[batch_start : batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(briefs) + BATCH_SIZE - 1) // BATCH_SIZE

            _status("generating_character_details", f"正在生成角色详情（{batch_num}/{total_batches}）...")

            details = await _ainvoke_section(
                self.outline_character_details_llm,
                (
                    "你是网络小说策划编辑。请为以下角色填充详细描述。\n"
                    f"{requirement_context}"
                    f"story：{json.dumps(story, ensure_ascii=False)}\n"
                    f"timeline：{_compact(timeline, limit=12)}\n"
                    f"全部角色概览：{json.dumps(briefs, ensure_ascii=False)}\n"
                    f"本批次需要填充的角色：{json.dumps(batch_briefs, ensure_ascii=False)}\n"
                    "必须调用 submit_character_details，不要输出普通文本。\n"
                    "为每个角色填充 appearance/personality/background/skills/current_status/current_goal。\n"
                    "角色字段必须是故事开始前状态。"
                ),
                "submit_character_details",
                "characters",
            )
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
                "必须调用 submit_foreshadowing，不要输出普通文本。"
                "foreshadowing 数量控制在 6-16。"
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
                "必须调用 submit_character_links，不要输出普通文本。"
                "每条记录必须包含 character_name、timeline_id、link_type。"
                "timeline_id 必须引用已有 timeline.id。"
                "link_type 只能是: appear, lead, conflict, ally, foreshadow_trigger, foreshadow_payoff。"
                "character_links 数量控制在 8-24。"
                "summary 可为空，若填写控制在 30 字以内。"
            ),
            "submit_character_links",
            "character_links",
        )

        return {
            "story": story,
            "timeline": timeline,
            "branches": branches,
            "foreshadowing": foreshadowing,
            "characters": characters,
            "character_links": character_links,
        }

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
        self, payload: OutlineQuickGenerateRequest, db: Session
    ) -> OutlineGenerateResponse:
        _ensure_demo_user(db)

        try:
            tags_str = "、".join(payload.tags) if payload.tags else "无特殊要求"
            result_dict = asyncio.run(
                self._generate_outline_sections(payload.idea.strip(), tags_str)
            )
            outline_tree = OutlineTreeData.model_validate(result_dict)
            outline_data = outline_tree.model_dump(mode="json")

            story = outline_data["story"]
            work = Work(
                user_id=DEMO_USER_ID,
                title=story["title"],
                genre=story["genre"],
                idea=payload.idea.strip(),
                tags=payload.tags,
                outline_tree=outline_data,
                status="草稿",
            )
            db.add(work)
            db.commit()
            db.refresh(work)

            # Create character records from outline
            characters_data = outline_data.get("characters", [])
            for char_data in characters_data:
                char = Character(
                    work_id=work.id,
                    name=char_data.get("name", ""),
                    role_type=char_data.get("role_type", "配角"),
                    gender=char_data.get("gender", ""),
                    age=char_data.get("age", ""),
                    appearance=char_data.get("appearance", ""),
                    personality=char_data.get("personality", ""),
                    background=char_data.get("background", ""),
                    skills=char_data.get("skills", ""),
                    current_status=char_data.get("current_status", "存活"),
                    current_goal=char_data.get("current_goal", ""),
                    first_chapter=char_data.get("first_chapter", 1),
                    last_chapter=char_data.get("first_chapter"),
                )
                db.add(char)
            db.commit()

            return OutlineGenerateResponse(outline_tree=outline_tree, work_id=work.id)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM outline generation failed: {exc}"
            ) from exc

    async def generate_outline_stream(self, payload: OutlineQuickGenerateRequest, emit):
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
            _ensure_demo_user(db)
            tags_str = "、".join(payload.tags) if payload.tags else "无特殊要求"
            result_dict = await self._generate_outline_sections(payload.idea.strip(), tags_str, emit=emit)
            emit("outline_status", {"phase": "parsing", "message": "正在解析并构建大纲树..."})

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
            work = Work(
                user_id=DEMO_USER_ID,
                title=story["title"],
                genre=story["genre"],
                idea=payload.idea.strip(),
                tags=payload.tags,
                outline_tree=outline_data,
                status="草稿",
            )
            db.add(work)
            t_db = time.perf_counter()
            db.commit()
            db.refresh(work)

            # Create character records from outline
            characters_data = outline_data.get("characters", [])
            for char_data in characters_data:
                char = Character(
                    work_id=work.id,
                    name=char_data.get("name", ""),
                    role_type=char_data.get("role_type", "配角"),
                    gender=char_data.get("gender", ""),
                    age=char_data.get("age", ""),
                    appearance=char_data.get("appearance", ""),
                    personality=char_data.get("personality", ""),
                    background=char_data.get("background", ""),
                    skills=char_data.get("skills", ""),
                    current_status=char_data.get("current_status", "存活"),
                    current_goal=char_data.get("current_goal", ""),
                    first_chapter=char_data.get("first_chapter", 1),
                    last_chapter=char_data.get("first_chapter"),
                )
                db.add(char)
            db.commit()
            logger.info(
                "work.generate_outline_stream db_done elapsed_ms=%.1f work_id=%s chars=%s",
                (time.perf_counter() - t_db) * 1000,
                work.id,
                len(characters_data),
            )

            emit("outline_done", {
                "work_id": work.id,
                "title": story["title"],
                "outline_tree": outline_data,
            })
            logger.info(
                "work.generate_outline_stream done total_ms=%.1f work_id=%s",
                (time.perf_counter() - t_total) * 1000,
                work.id,
            )
        except Exception as exc:
            logger.exception("outline streaming failed")
            emit("error", {"message": str(exc)})
        finally:
            db.close()

    def update_outline(self, work_id: str, outline_tree: dict, db: Session) -> WorkOut:
        """Directly save an outline tree (from user inline editing)."""
        work = db.query(Work).filter_by(id=work_id).first()
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
        session_id: str | None = None,
    ) -> ChatEditResponse:
        """Synchronous outline chat edit using Tool-Calling loop."""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        from app.services.outline_tools import ALL_OUTLINE_TOOLS

        work = db.query(Work).filter_by(id=work_id).first()
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
    ) -> ChatEditResponse:
        """Async outline chat edit using Tool-Calling loop.

        Replaces the old JSON output approach (with_structured_output) with native
        LLM tool-calling, eliminating field name inconsistencies (e.g. 'name' vs 'tool').

        Args:
            dry_run: 如果为 True，工具正常执行但最后不 commit。
                     调用方负责在确认后 commit 或 rollback。
        """
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        from app.services.outline_tools import ALL_OUTLINE_TOOLS

        work = db.query(Work).filter_by(id=work_id).first()
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
        max_iterations = 10

        try:
            for _ in range(max_iterations):
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

    def generate_chapter(self, work_id: str, chapter_number: int, db: Session) -> ChapterGenerateResponse:
        work = db.query(Work).filter_by(id=work_id).first()
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
                summary = ch.content[:800] + ("..." if len(ch.content) > 800 else "")
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
                chapter.status = "草稿"
            else:
                chapter = Chapter(
                    work_id=work_id,
                    chapter_number=chapter_number,
                    title=title or f"第{chapter_number}章",
                    content=body,
                    status="草稿",
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
    def list_chapters(work_id: str, db: Session) -> list[ChapterOut]:
        work = db.query(Work).filter_by(id=work_id).first()
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
    def get_chapter(work_id: str, chapter_number: int, db: Session) -> ChapterOut:
        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        return ChapterOut.model_validate(chapter)

    @staticmethod
    def update_chapter(work_id: str, chapter_number: int, payload: ChapterUpdateRequest, db: Session) -> ChapterOut:
        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        if payload.title is not None:
            chapter.title = payload.title
        if payload.content is not None:
            chapter.content = payload.content
            chapter.status = "已保存"
        db.commit()
        db.refresh(chapter)
        return ChapterOut.model_validate(chapter)

    @staticmethod
    def get_chapter_intel(work_id: str, chapter_number: int, db: Session) -> ChapterIntelOut:
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
    ) -> ChapterChatResponse:
        """Use LLM to edit chapter content via conversation (DEPRECATED — use edit_chapter via SupervisorAgent)."""
        work = db.query(Work).filter_by(id=work_id).first()
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
                            "proposed_content_preview": (proposed_content or "")[:300]})

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
    def list_works(db: Session) -> list[WorkOut]:
        _ensure_demo_user(db)
        works = (
            db.query(Work)
            .filter_by(user_id=DEMO_USER_ID)
            .order_by(Work.created_at.desc())
            .all()
        )
        return [WorkOut.model_validate(w) for w in works]

    @staticmethod
    def get_work(work_id: str, db: Session) -> WorkOut:
        work = db.query(Work).filter_by(id=work_id).first()
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
    def delete_work(work_id: str, db: Session) -> None:
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        db.delete(work)
        db.commit()
