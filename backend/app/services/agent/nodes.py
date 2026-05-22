"""LangGraph node implementations for the chapter writing agent."""

import json
import re
from pathlib import Path

from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.work_model import Chapter, Character, Work
from app.services.agent.state import AgentGraphState
from app.services.work_service import WorkService

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompt_templates"


def _read_prompt(file_name: str) -> str:
    return (PROMPT_DIR / file_name).read_text(encoding="utf-8")


def _get_llm(temperature: float = 0.7) -> ChatOpenAI:
    model_conf = settings.get_model_config()
    return ChatOpenAI(
        model=settings.default_model,
        api_key=model_conf["api_key"],
        base_url=model_conf["base_url"],
        temperature=temperature,
        streaming=True,
    )


def _word_count(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def _prepare_context(state: AgentGraphState, db: Session) -> None:
    """Shared helper: populate story_info, outline_tree, chapter_outline, previous_chapters."""
    if state.outline_tree:
        return
    work = db.query(Work).filter_by(id=state.work_id).first()
    if not work:
        return
    outline_tree = work.outline_tree
    state.story_info = json.dumps(outline_tree.get("story", {}), ensure_ascii=False)
    state.outline_tree = json.dumps(outline_tree, ensure_ascii=False, indent=2)
    state.chapter_outline = WorkService._find_chapter_outline(outline_tree, state.chapter_number)

    prev_chapters = (
        db.query(Chapter)
        .filter_by(work_id=state.work_id)
        .filter(Chapter.chapter_number < state.chapter_number)
        .filter(Chapter.content != "")
        .order_by(Chapter.chapter_number.desc())
        .limit(3)
        .all()
    )
    prev_chapters.reverse()
    if prev_chapters:
        parts = []
        for ch in prev_chapters:
            summary = ch.content[:800] + ("..." if len(ch.content) > 800 else "")
            parts.append(f"--- 第{ch.chapter_number}章 {ch.title} ---\n{summary}")
        state.previous_chapters = "\n\n".join(parts)
    else:
        state.previous_chapters = "（这是第一章，暂无前文）"


# ──────────────────────────── plan node ────────────────────────────

async def plan_node(state: AgentGraphState, emit, db: Session) -> AgentGraphState:
    """Node 0: Generate a concise writing plan before detailed thinking."""
    emit("stage_start", {"stage": "plan", "label": "规划阶段"})

    _prepare_context(state, db)

    instruction_context = state.user_instruction if state.user_instruction else "（无特殊要求）"
    if state.confirm_feedback:
        instruction_context += f"\n\n用户反馈：{state.confirm_feedback}"

    template = _read_prompt("agent_plan.txt")
    prompt = PromptTemplate.from_template(template)
    llm = _get_llm(temperature=0.6)

    chain = prompt | llm

    raw_output = ""
    async for chunk in chain.astream({
        "chapter_number": str(state.chapter_number),
        "story_info": state.story_info,
        "outline_tree": state.outline_tree,
        "chapter_outline": state.chapter_outline,
        "previous_chapters": state.previous_chapters,
        "user_instruction": instruction_context,
    }):
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        raw_output += text
        emit("plan_stream", {"chunk": text})

    state.plan_text = raw_output.strip()
    emit("plan_done", {"plan": state.plan_text})
    return state


# ──────────────────────────── thinking node ────────────────────────────

async def thinking_node(state: AgentGraphState, emit, db: Session) -> AgentGraphState:
    """Node 1: Generate thinking notes and chapter title for the chapter.
    Includes self-review mechanism and selective query markers."""
    emit("stage_start", {"stage": "thinking", "label": "构思阶段"})

    _prepare_context(state, db)

    # Build user instruction context
    instruction_context = state.user_instruction if state.user_instruction else "（无特殊要求）"
    if state.confirm_feedback:
        instruction_context += f"\n\n用户反馈：{state.confirm_feedback}"

    template = _read_prompt("agent_thinking.txt")
    prompt = PromptTemplate.from_template(template)
    llm = _get_llm(temperature=0.8)

    chain = prompt | llm

    # Stream the thinking process — filter out JSON metadata in real-time
    raw_output = ""
    json_started = False  # True once we detect the start of the JSON metadata block
    pre_json_text = ""    # text accumulated before JSON starts

    async for chunk in chain.astream({
        "chapter_number": str(state.chapter_number),
        "story_info": state.story_info,
        "outline_tree": state.outline_tree,
        "chapter_outline": state.chapter_outline,
        "previous_chapters": state.previous_chapters,
        "plan_text": state.plan_text or "（无规划，请自行构思）",
        "user_instruction": instruction_context,
    }):
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        raw_output += text

        if not json_started:
            # Check if the accumulated output now contains the start of the JSON block.
            # Two patterns: fenced (```json {) or bare ({ on a new line after markdown).
            fence_start = re.search(r"```(?:json)?\s*\n?\s*\{", raw_output)
            bare_start = re.search(r"(?<!\w)\{\s*\n\s*\"title\"", raw_output)

            if fence_start:
                json_started = True
                pre_json_text = raw_output[:fence_start.start()].strip()
                # Don't emit any more chunks — JSON is being generated
            elif bare_start:
                json_started = True
                pre_json_text = raw_output[:bare_start.start()].strip()
            else:
                # Still in thinking text — emit the chunk
                # But buffer: don't emit text that might be the start of JSON
                # Use a lookback window: hold back the last 20 chars in case they're
                # the start of ```json or {"title"
                safe_end = len(raw_output)
                if len(raw_output) > 20:
                    # Check if there's a potential incomplete fence/JSON start in the tail
                    tail = raw_output[-30:]
                    if re.search(r"```[a-z]*$", tail) or re.search(r"\{\s*$", tail):
                        safe_end = len(raw_output) - 10
                if safe_end > len(pre_json_text):
                    emit_text = raw_output[len(pre_json_text):safe_end]
                    if emit_text:
                        pre_json_text = raw_output[:safe_end]
                        emit("thinking_stream", {"chunk": emit_text})

    # If JSON was never detected, the entire output is thinking text
    if not json_started:
        pre_json_text = raw_output

    # Parse the required JSON metadata from the full output.
    notes = pre_json_text
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
    if not json_match:
        json_match = re.search(r"\{[\s\S]*\"title\"[\s\S]*\}", raw_output)
    if not json_match:
        raise ValueError("构思阶段输出缺少必需的 JSON 元数据块")

    result = json.loads(json_match.group(1) if json_match.lastindex else json_match.group())
    if not isinstance(result, dict):
        raise ValueError("构思阶段 JSON 元数据必须是对象")

    required_fields = {
        "title",
        "outline_changes_needed",
        "outline_change_reason",
        "outline_change_operations",
        "needed_queries",
    }
    missing_fields = sorted(required_fields - set(result))
    if missing_fields:
        raise ValueError(f"构思阶段 JSON 元数据缺少字段：{', '.join(missing_fields)}")

    title = result["title"]
    outline_changes_needed = result["outline_changes_needed"]
    outline_change_reason = result["outline_change_reason"]
    outline_change_operations = result["outline_change_operations"]
    needed_queries = result["needed_queries"]

    if not isinstance(title, str):
        raise ValueError("构思阶段 JSON 字段 title 必须是字符串")
    if not isinstance(outline_changes_needed, bool):
        raise ValueError("构思阶段 JSON 字段 outline_changes_needed 必须是布尔值")
    if not isinstance(outline_change_reason, str):
        raise ValueError("构思阶段 JSON 字段 outline_change_reason 必须是字符串")
    if not isinstance(outline_change_operations, list):
        raise ValueError("构思阶段 JSON 字段 outline_change_operations 必须是数组")
    if not isinstance(needed_queries, list):
        raise ValueError("构思阶段 JSON 字段 needed_queries 必须是数组")

    state.thinking_notes = notes
    state.chapter_title = title
    state.outline_changes_needed = outline_changes_needed
    state.outline_change_reason = outline_change_reason
    state.outline_change_operations = outline_change_operations
    state.needed_queries = needed_queries

    emit("thinking_done", {"notes": notes})
    emit("title_proposed", {"title": title})

    if state.needed_queries:
        emit("queries_needed", {"queries": state.needed_queries})

    # If outline changes are proposed, queue for confirmation
    if outline_changes_needed and outline_change_operations:
        state.pending_confirm = "outline"
        emit("outline_proposal", {
            "reason": outline_change_reason,
            "operations": outline_change_operations,
        })

    return state


# ──────────────────────────── query node ────────────────────────────

async def query_node(state: AgentGraphState, emit, db: Session) -> AgentGraphState:
    """Node 2: Gather context from previous chapters, characters, and consistency checks.
    If needed_queries is set, performs targeted queries instead of dumping everything."""
    emit("stage_start", {"stage": "query", "label": "查询上下文"})

    work = db.query(Work).filter_by(id=state.work_id).first()
    if not work:
        state.error = "作品不存在"
        return state

    context_parts = []

    # If thinking node specified needed queries, do targeted search
    if state.needed_queries:
        for query_item in state.needed_queries:
            query_lower = query_item.lower()

            # Search in foreshadowing
            foreshadowing = work.outline_tree.get("foreshadowing", [])
            for f in foreshadowing:
                if any(kw in f.get("content", "").lower() or kw in f.get("id", "").lower()
                       for kw in query_lower.split()):
                    entry = f"伏笔 {f.get('id', '')}：{f.get('content', '')}（埋设于{f.get('plant_node', '')}，回收于{f.get('payoff_node', '')}）"
                    context_parts.append(entry)
                    emit("query_result", {"source": f"伏笔 {f.get('id', '')} [按需]", "summary": f.get('content', '')})

            # Search in characters
            characters = db.query(Character).filter_by(work_id=state.work_id).all()
            for c in characters:
                if c.name in query_item or query_lower in c.name.lower():
                    char_text = (
                        f"【{c.name}】{c.role_type}，{c.gender}，{c.age}。"
                        f"性格：{c.personality}。背景：{c.background}。"
                        f"技能：{c.skills}。当前状态：{c.current_status}。"
                        f"当前目的：{c.current_goal}。"
                    )
                    context_parts.append(char_text)
                    emit("query_result", {
                        "source": f"角色 {c.name} [按需]",
                        "summary": f"{c.role_type}，状态：{c.current_status}",
                    })

            # Search in previous chapters
            prev_chapters = (
                db.query(Chapter)
                .filter_by(work_id=state.work_id)
                .filter(Chapter.chapter_number < state.chapter_number)
                .filter(Chapter.content != "")
                .order_by(Chapter.chapter_number)
                .all()
            )
            for ch in prev_chapters:
                if any(kw in ch.content.lower() or kw in (ch.title or "").lower()
                       for kw in query_lower.split()):
                    summary = ch.content[:600] + ("..." if len(ch.content) > 600 else "")
                    context_parts.append(f"第{ch.chapter_number}章 {ch.title}：{summary}")
                    emit("query_result", {"source": f"第{ch.chapter_number}章 {ch.title} [按需]", "summary": summary})
    else:
        # Fallback: query everything (original behavior)
        prev_chapters = (
            db.query(Chapter)
            .filter_by(work_id=state.work_id)
            .filter(Chapter.chapter_number < state.chapter_number)
            .filter(Chapter.content != "")
            .order_by(Chapter.chapter_number)
            .all()
        )

        for ch in prev_chapters:
            summary = ch.content[:600] + ("..." if len(ch.content) > 600 else "")
            entry = f"第{ch.chapter_number}章 {ch.title}：{summary}"
            context_parts.append(entry)
            emit("query_result", {"source": f"第{ch.chapter_number}章 {ch.title}", "summary": summary})

        # Story settings from outline
        story = work.outline_tree.get("story", {})
        story_setting = f"标题：{story.get('title', '')}，类型：{story.get('genre', '')}，卷：{story.get('volume', '')}"
        context_parts.append(f"作品设定：{story_setting}")
        emit("query_result", {"source": "作品设定", "summary": story_setting})

        # Foreshadowing info
        foreshadowing = work.outline_tree.get("foreshadowing", [])
        if foreshadowing:
            for f in foreshadowing:
                entry = f"伏笔 {f.get('id', '')}：{f.get('content', '')}（埋设于{f.get('plant_node', '')}，回收于{f.get('payoff_node', '')}）"
                context_parts.append(entry)
                emit("query_result", {"source": f"伏笔 {f.get('id', '')}", "summary": f.get('content', '')})

    # Always include character info for relevant characters
    characters = db.query(Character).filter_by(work_id=state.work_id).all()
    if characters:
        relevant_chars = [
            c for c in characters
            if c.first_chapter is None or c.first_chapter <= state.chapter_number
        ]
        # Deduplicate: skip chars already queried via needed_queries
        already_queried = set()
        if state.needed_queries:
            for q in state.needed_queries:
                for c in characters:
                    if c.name in q:
                        already_queried.add(c.name)

        new_chars = [c for c in relevant_chars if c.name not in already_queried]
        if new_chars:
            char_parts = []
            for c in new_chars:
                char_text = (
                    f"【{c.name}】{c.role_type}，{c.gender}，{c.age}。"
                    f"性格：{c.personality}。背景：{c.background}。"
                    f"技能：{c.skills}。当前状态：{c.current_status}。"
                    f"当前目的：{c.current_goal}。"
                )
                char_parts.append(char_text)
                emit("query_result", {
                    "source": f"角色 {c.name}",
                    "summary": f"{c.role_type}，状态：{c.current_status}，目的：{c.current_goal}",
                })
            context_parts.append("## 角色设定\n" + "\n".join(char_parts))

    state.context_pack = "\n\n".join(context_parts)
    mode = "按需" if state.needed_queries else "全量"
    emit("query_done", {"summary": f"已查询（{mode}）— {len(context_parts)} 条上下文"})
    return state


# ──────────────────────────── write node ────────────────────────────

async def write_node(state: AgentGraphState, emit, db: Session) -> AgentGraphState:
    """Node 3: Write the chapter content with streaming."""
    emit("stage_start", {"stage": "write", "label": "撰写正文"})

    template = _read_prompt("agent_write.txt")
    prompt = PromptTemplate.from_template(template)
    llm = _get_llm(temperature=0.7)

    chain = prompt | llm

    # Stream the raw LLM output as pure text
    raw_output = ""
    async for chunk in chain.astream({
        "chapter_number": str(state.chapter_number),
        "story_info": state.story_info,
        "outline_tree": state.outline_tree,
        "chapter_outline": state.chapter_outline,
        "chapter_title": state.chapter_title,
        "thinking_notes": state.thinking_notes,
        "context_pack": state.context_pack,
        "previous_chapters": state.previous_chapters,
    }):
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        raw_output += text
        emit("write_stream", {"chunk": text})

    state.chapter_content = raw_output

    emit("write_done", {
        "title": state.chapter_title,
        "content": state.chapter_content,
        "word_count": _word_count(state.chapter_content),
    })
    return state


# ──────────────────────────── outline edit node ────────────────────────────

async def outline_edit_node(state: AgentGraphState, emit, db: Session) -> AgentGraphState:
    """Node: Apply approved outline changes."""
    emit("stage_start", {"stage": "outline_edit", "label": "更新大纲"})

    work = db.query(Work).filter_by(id=state.work_id).first()
    if not work:
        state.error = "作品不存在"
        return state

    from app.services.work_service import WorkService
    svc = WorkService()
    updated_outline = svc._apply_operations(work.outline_tree, state.outline_change_operations)

    story = updated_outline.get("story", {})
    work.outline_tree = updated_outline
    work.title = story.get("title", work.title)
    work.genre = story.get("genre", work.genre)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    # Update state with new outline
    state.outline_tree = json.dumps(updated_outline, ensure_ascii=False, indent=2)
    state.outline_changes_needed = False
    state.outline_change_operations = []
    state.outline_change_reason = ""
    state.pending_confirm = ""

    emit("outline_updated", {"message": "大纲已更新"})
    return state


# ──────────────────────────── save node ────────────────────────────

async def save_node(state: AgentGraphState, emit, db: Session) -> AgentGraphState:
    """Node 4: Save the chapter to database."""
    emit("stage_start", {"stage": "save", "label": "保存章节"})

    if not state.chapter_content:
        state.error = "没有可保存的内容"
        emit("error", {"message": state.error})
        return state

    chapter = db.query(Chapter).filter_by(
        work_id=state.work_id, chapter_number=state.chapter_number
    ).first()

    if chapter:
        chapter.title = state.chapter_title or chapter.title
        chapter.content = state.chapter_content
        chapter.status = "草稿"
    else:
        chapter = Chapter(
            work_id=state.work_id,
            chapter_number=state.chapter_number,
            title=state.chapter_title or f"第{state.chapter_number}章",
            content=state.chapter_content,
            status="草稿",
        )
        db.add(chapter)

    try:
        db.commit()
        db.refresh(chapter)
    except Exception as exc:
        db.rollback()
        state.error = f"保存章节失败：{exc!r}"
        emit("error", {"message": state.error})
        return state

    state.saved = True
    emit("saved", {
        "chapter_number": state.chapter_number,
        "title": chapter.title,
        "word_count": _word_count(chapter.content),
    })
    emit("done", {"message": "章节已保存"})
    return state


# ──────────────────────────── update characters node ────────────────────────────

async def update_characters_node(state: AgentGraphState, emit, db: Session) -> AgentGraphState:
    """Node: After saving, analyze the chapter to update character states."""
    from pydantic import BaseModel as PydanticBase, Field

    class CharacterUpdateNode(PydanticBase):
        name: str = Field(description="角色名")
        current_status: str = Field(default="", description="新状态")
        current_goal: str = Field(default="", description="新目的")
        last_location: str = Field(default="", description="新位置")

    class CharacterUpdatesNodeResult(PydanticBase):
        character_updates: list[CharacterUpdateNode] = Field(default_factory=list)

    emit("stage_start", {"stage": "update_characters", "label": "更新角色状态"})

    characters = db.query(Character).filter_by(work_id=state.work_id).all()
    if not characters:
        emit("characters_updated", {"message": "无角色需要更新"})
        return state

    # Build character list for the LLM
    char_list = []
    for c in characters:
        char_list.append(f"- {c.name}（{c.role_type}）：当前状态={c.current_status}，目的={c.current_goal}，最后位置={c.last_location}")

    char_text = "\n".join(char_list)

    template = _read_prompt("agent_update_characters.txt")
    prompt = PromptTemplate.from_template(template)
    llm = _get_llm(temperature=0.3)
    structured_llm = llm.with_structured_output(CharacterUpdatesNodeResult)

    chain = prompt | structured_llm

    try:
        result = await chain.ainvoke({
            "chapter_number": str(state.chapter_number),
            "chapter_title": state.chapter_title,
            "chapter_content": state.chapter_content[:3000],
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
            char.last_chapter = state.chapter_number
            updated_names.append(char_name)

        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        emit("characters_updated", {
            "message": f"已更新 {len(updated_names)} 个角色状态",
            "updated": updated_names,
        })
    except Exception as exc:
        db.rollback()
        emit("characters_updated", {"message": f"角色状态更新跳过：{exc}"})

    return state
