"""LangGraph node implementations for the chapter writing agent."""

import json
import re
from pathlib import Path

from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.work_model import Chapter, Work
from app.services.agent.state import AgentGraphState
from app.services.work_service import WorkService

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompt_templates"


def _read_prompt(file_name: str) -> str:
    return (PROMPT_DIR / file_name).read_text(encoding="utf-8")


def _get_llm(temperature: float = 0.7) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=temperature,
        streaming=True,
    )


def _word_count(text: str) -> int:
    return len(re.sub(r"\s", "", text))


# ──────────────────────────── thinking node ────────────────────────────

async def thinking_node(state: AgentGraphState, emit, db: Session) -> AgentGraphState:
    """Node 1: Generate thinking notes for the chapter."""
    emit("stage_start", {"stage": "thinking", "label": "构思阶段"})

    work = db.query(Work).filter_by(id=state.work_id).first()
    if not work:
        state.error = "作品不存在"
        return state

    outline_tree = work.outline_tree
    story_info = json.dumps(outline_tree.get("story", {}), ensure_ascii=False)
    outline_text = json.dumps(outline_tree, ensure_ascii=False, indent=2)
    chapter_outline = WorkService._find_chapter_outline(outline_tree, state.chapter_number)

    # Collect previous chapters
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
        previous_text = "\n\n".join(parts)
    else:
        previous_text = "（这是第一章，暂无前文）"

    # Build user instruction context
    instruction_context = state.user_instruction if state.user_instruction else "（无特殊要求）"
    if state.confirm_feedback:
        instruction_context += f"\n\n用户反馈：{state.confirm_feedback}"

    template = _read_prompt("agent_thinking.txt")
    prompt = PromptTemplate.from_template(template)
    llm = _get_llm(temperature=0.8)

    chain = prompt | llm

    # Stream the thinking process
    notes = ""
    async for chunk in chain.astream({
        "chapter_number": str(state.chapter_number),
        "story_info": story_info,
        "outline_tree": outline_text,
        "chapter_outline": chapter_outline,
        "previous_chapters": previous_text,
        "user_instruction": instruction_context,
    }):
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        notes += text
        emit("thinking_stream", {"chunk": text})

    state.thinking_notes = notes
    state.story_info = story_info
    state.outline_tree = outline_text
    state.chapter_outline = chapter_outline
    state.previous_chapters = previous_text

    emit("thinking_done", {"notes": notes})
    return state


# ──────────────────────────── query node ────────────────────────────

async def query_node(state: AgentGraphState, emit, db: Session) -> AgentGraphState:
    """Node 2: Gather context from previous chapters and consistency checks."""
    emit("stage_start", {"stage": "query", "label": "查询上下文"})

    work = db.query(Work).filter_by(id=state.work_id).first()
    if not work:
        state.error = "作品不存在"
        return state

    context_parts = []

    # Query previous chapters for details
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

    state.context_pack = "\n\n".join(context_parts)
    emit("query_done", {"summary": f"已查询 {len(prev_chapters)} 章前文、{len(foreshadowing)} 条伏笔"})
    return state


# ──────────────────────────── write node ────────────────────────────

async def write_node(state: AgentGraphState, emit, db: Session) -> AgentGraphState:
    """Node 3: Write the chapter content with streaming."""
    emit("stage_start", {"stage": "write", "label": "撰写正文"})

    template = _read_prompt("agent_write.txt")
    prompt = PromptTemplate.from_template(template)
    llm = _get_llm(temperature=0.7)

    chain = prompt | llm

    # Stream the raw LLM output
    raw_output = ""
    async for chunk in chain.astream({
        "chapter_number": str(state.chapter_number),
        "story_info": state.story_info,
        "outline_tree": state.outline_tree,
        "chapter_outline": state.chapter_outline,
        "thinking_notes": state.thinking_notes,
        "context_pack": state.context_pack,
        "previous_chapters": state.previous_chapters,
    }):
        text = chunk.content if hasattr(chunk, "content") else str(chunk)
        raw_output += text
        emit("write_stream", {"chunk": text})

    # Parse the JSON output
    try:
        # Extract JSON from the output (may be wrapped in markdown code block)
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(1))
        else:
            # Try to find raw JSON
            json_match = re.search(r"\{[\s\S]*\"title\"[\s\S]*\"content\"[\s\S]*\}", raw_output)
            if json_match:
                result = json.loads(json_match.group())
            else:
                # Fallback: treat entire output as content with default title
                result = {
                    "title": f"第{state.chapter_number}章",
                    "content": raw_output,
                    "outline_changes_needed": False,
                }
    except (json.JSONDecodeError, Exception):
        result = {
            "title": f"第{state.chapter_number}章",
            "content": raw_output,
            "outline_changes_needed": False,
        }

    state.chapter_title = result.get("title", f"第{state.chapter_number}章")
    state.chapter_content = result.get("content", "")
    state.outline_changes_needed = result.get("outline_changes_needed", False)
    state.outline_change_reason = result.get("outline_change_reason", "")
    state.outline_change_operations = result.get("outline_change_operations", [])

    if state.outline_changes_needed and state.outline_change_operations:
        state.pending_confirm = "outline"
        emit("outline_proposal", {
            "reason": state.outline_change_reason,
            "operations": state.outline_change_operations,
        })

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
    db.commit()

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
        chapter.status = "已生成"
    else:
        chapter = Chapter(
            work_id=state.work_id,
            chapter_number=state.chapter_number,
            title=state.chapter_title or f"第{state.chapter_number}章",
            content=state.chapter_content,
            status="已生成",
        )
        db.add(chapter)

    db.commit()
    db.refresh(chapter)

    state.saved = True
    emit("saved", {
        "chapter_number": state.chapter_number,
        "title": chapter.title,
        "word_count": _word_count(chapter.content),
    })
    emit("done", {"message": "章节已保存"})
    return state
