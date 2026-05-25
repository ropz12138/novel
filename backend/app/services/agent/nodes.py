"""LangGraph node implementations for the chapter writing agent."""

import json
import re
from pathlib import Path

from langchain_core.prompts import PromptTemplate
from app.core.deepseek_llm import DeepSeekChatOpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.work_model import Chapter, Character, Work
from app.services.agent.state import AgentGraphState
from app.services.work_service import WorkService

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompt_templates"


def _read_prompt(file_name: str) -> str:
    return (PROMPT_DIR / file_name).read_text(encoding="utf-8")


def _get_llm(temperature: float = 0.7) -> DeepSeekChatOpenAI:
    model_conf = settings.get_model_config()
    return DeepSeekChatOpenAI(
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
    """Node 1: Generate thinking notes for the chapter."""
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

    # Stream the thinking process as plain markdown notes.
    raw_output = ""

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
        emit("thinking_stream", {"chunk": text})

    notes = raw_output.strip()
    state.thinking_notes = notes
    state.chapter_title = state.chapter_title or f"第{state.chapter_number}章"
    state.outline_changes_needed = False
    state.outline_change_reason = ""
    state.outline_change_operations = []
    state.needed_queries = []

    emit("thinking_done", {"notes": notes})

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
        chapter.status = "已保存"
    else:
        chapter = Chapter(
            work_id=state.work_id,
            chapter_number=state.chapter_number,
            title=state.chapter_title or f"第{state.chapter_number}章",
            content=state.chapter_content,
            status="已保存",
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
