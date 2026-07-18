"""章节工具 - 生成和编辑章节"""
import json
import asyncio
import logging
import re
from typing import Optional
from functools import partial

from langchain_core.tools import StructuredTool
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.node import Node
from app.models.edge import Edge
from app.models.chapter import Chapter
from app.services.context_builder import build_generation_context
from app.services.chapter_generator import generate_chapter
from app.services.agents.tools.node_tools import _compact, _neighbor_items, _get_emit

logger = logging.getLogger(__name__)


def _get_db():
    """获取数据库会话"""
    from app.database import SessionLocal
    return SessionLocal()


def _get_current_work_id():
    """获取当前work_id"""
    try:
        from app.services.agents.supervisor import get_context
        return get_context().get("work_id")
    except:
        return None


# 输入Schema
class CreateChapterUnderMicroInput(BaseModel):
    micro_node_id: str = Field(description="父小纲节点ID")
    title: str = Field(description="章节标题")
    relationship_type: str = Field(default="main_plot", description="关系类型：用简短自然语言描述章节与小纲的关系（如'主要情节推进'、'伏笔埋设'、'场景过渡'等，不超过100字符）")
    content: str = Field(default="", description="章节内容（可选）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class GenerateChapterContentInput(BaseModel):
    chapter_node_id: str = Field(description="章节节点ID")
    extra_instructions: str = Field(default="", description="额外的写作指令")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class EditChapterContentInput(BaseModel):
    chapter_node_id: str = Field(description="章节节点ID")
    edit_instruction: str = Field(description="编辑指令（用户原话，不准改写）")
    context: str = Field(default="", description="写作上下文原文：大纲/角色/伏笔等 agent 已备齐的素材")
    prev_chapter_node_id: Optional[str] = Field(default=None, description="上一章节点ID，用于承接连贯性；开篇章节不传")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class SummarizeChapterInput(BaseModel):
    chapter_node_id: str = Field(description="章节节点ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class GetChapterContextInput(BaseModel):
    chapter_node_id: str = Field(description="章节节点ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class CheckChapterConsistencyInput(BaseModel):
    chapter_node_id: str = Field(description="章节节点ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


# 同步实现
def _create_chapter_under_micro_sync(micro_node_id, title, relationship_type="main_plot", content="", reason=None):
    """在小纲节点下创建章节节点"""
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
    
    # 验证关系类型：允许自然语言，限制长度
    if len(relationship_type.strip()) == 0:
        return json.dumps({"error": "关系类型不能为空"}, ensure_ascii=False)
    if len(relationship_type) > 100:
        return json.dumps({"error": "关系类型不能超过100字符"}, ensure_ascii=False)
    
    db = _get_db()
    try:
        # 验证小纲节点
        micro_node = db.query(Node).filter(
            Node.id == micro_node_id,
            Node.work_id == work_id,
            Node.type == "micro_outline"
        ).first()
        if not micro_node:
            return json.dumps({"error": "小纲节点不存在"}, ensure_ascii=False)
        
        # 计算位置（在小纲下方）
        siblings = db.query(Node).join(Edge, Edge.target_id == Node.id).filter(
            Edge.source_id == micro_node_id,
            Edge.edge_type == "contains"
        ).order_by(Node.position_x).all()
        
        if siblings:
            position_x = siblings[-1].position_x + 200
        else:
            position_x = micro_node.position_x
        position_y = micro_node.position_y + 200
        
        # 创建章节节点
        import uuid
        node = Node(
            id=str(uuid.uuid4()),
            work_id=work_id,
            type="chapter",
            title=title,
            content=content,
            position_x=position_x,
            position_y=position_y,
        )
        db.add(node)
        db.flush()
        
        # 建立关系连线（使用指定的关系类型）
        edge = Edge(
            id=str(uuid.uuid4()),
            work_id=work_id,
            source_id=micro_node_id,
            target_id=node.id,
            edge_type=relationship_type,
            label=relationship_type
        )
        db.add(edge)
        
        # 与上一个兄弟节点建立顺序连线
        if siblings:
            seq_edge = Edge(
                id=str(uuid.uuid4()),
                work_id=work_id,
                source_id=siblings[-1].id,
                target_id=node.id,
                edge_type="inherits",
                label="顺序"
            )
            db.add(seq_edge)
        
        db.commit()
        db.refresh(node)
        
        return json.dumps({
            "success": True,
            "chapter_node_id": node.id,
            "title": title,
            "message": f"已创建章节「{title}」",
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _generate_chapter_content_sync(chapter_node_id, extra_instructions="", reason=None):
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == chapter_node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        if node.type != "chapter":
            return json.dumps({"error": "只能对章节节点生成内容"}, ensure_ascii=False)
        context = build_generation_context(db, chapter_node_id, extra_instructions)
        result = generate_chapter(context)
        node.content = result["content"]
        chapter = db.query(Chapter).filter(Chapter.node_id == chapter_node_id).first()
        if not chapter:
            chapter = Chapter(node_id=chapter_node_id, work_id=node.work_id)
            db.add(chapter)
        chapter.summary = result["summary"]
        chapter.new_facts = result["new_facts"]
        chapter.foreshadows = result["foreshadows"]
        chapter.generation_context = context
        db.commit()
        return json.dumps({
            "success": True, "chapter_node_id": chapter_node_id,
            "content": result["content"], "summary": result["summary"],
            "new_facts": result["new_facts"], "foreshadows": result["foreshadows"],
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


_EDIT_CHAPTER_SYSTEM = """你是小说正文编辑助手。任务：按用户指令对已有章节做最小范围修改。

【铁律】
1. "用户编辑指令"是用户原话，逐字遵守，禁止擅自扩写无关内容。
2. 只修改与指令直接相关的段落，其余段落不得改动。
3. 输出必须是合法 JSON，且仅包含 JSON，格式见说明；禁止输出 JSON 以外的任何文字。
4. old_text 必须从原文精确复制，用于后端校验。
5. 保持第三人称叙事风格，与原文一致。
6. 禁止生成提纲、规划性文字。

【输出格式】
{
  "edits": [
    {
      "type": "replace",
      "paragraph_index": 3,
      "old_text": "从原文精确复制的待改片段或整段",
      "new_text": "修改后的文本"
    },
    {
      "type": "insert_after",
      "paragraph_index": 2,
      "new_text": "插入的新段落全文"
    },
    {
      "type": "delete",
      "paragraph_index": 5,
      "old_text": "待删除段落的完整原文"
    }
  ]
}

type 取值：replace（替换）、insert_after（在 paragraph_index 段后插入；0 表示文首前插入）、delete（删除整段，old_text 必须与该段全文一致）。
paragraph_index 为 1-based，与正文中 [N] 段落编号一致。"""


def _format_numbered_paragraphs(content: str) -> str:
    from app.services.chapter_edit_service import split_paragraphs

    paragraphs = split_paragraphs(content)
    if not paragraphs:
        return "（空）"
    return "\n\n".join(f"[{i + 1}] {p}" for i, p in enumerate(paragraphs))


def _build_edit_chapter_messages(
    edit_instruction,
    content,
    context,
    global_context="",
    prev_chapter="",
    elements=None,
):
    system = _EDIT_CHAPTER_SYSTEM
    if global_context:
        system = global_context + "\n\n" + system

    sections = [
        "======= 用户编辑指令（最高优先级，逐字遵守，禁止改写扩写）=======\n"
        f"{edit_instruction}\n"
        "=====================================================================",
        "======= 当前章节正文（按段落编号）=======\n"
        f"{_format_numbered_paragraphs(content)}\n"
        "=========================================",
    ]
    if prev_chapter:
        sections.append(
            "======= 上一章正文（承接参考）=======\n"
            f"{prev_chapter}\n"
            "====================================="
        )
    if elements:
        elem_text = "\n".join(f"- {e['title']}：{e['content']}" for e in elements)
        sections.append(
            "======= 本章情节元素（修改时勿破坏已涵盖的情节）=======\n"
            f"{elem_text}\n"
            "======================================================"
        )
    if context:
        sections.append(
            "======= 写作上下文（agent 已备齐，直接使用）=======\n"
            f"{context}\n"
            "================================================="
        )

    human = "\n\n".join(sections)
    return [SystemMessage(content=system), HumanMessage(content=human)]


def _parse_edits_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    data = json.loads(text)
    if not isinstance(data, dict) or "edits" not in data:
        raise ValueError("LLM 输出缺少 edits 字段")
    if not isinstance(data["edits"], list):
        raise ValueError("edits 必须是数组")
    return data


async def _edit_chapter_content_coroutine(
    chapter_node_id,
    edit_instruction,
    context="",
    reason=None,
    work_id=None,
    prev_chapter_node_id=None,
) -> str:
    from app.services.agents.llm import get_llm, context_model_pref_kwargs
    from app.services.chapter_edit_service import (
        apply_edits,
        build_chapter_edit_diff,
        split_paragraphs,
        validate_edits,
    )
    from app.services.chapter_history_service import clear_chapter_summary_on_content_change
    from app.services.chapter_word_count import chapter_body_word_count
    from app.services.global_context import get_global_nodes, format_global_context
    from app.services.llm_stream import chunk_to_ai_message, emit_llm_stream_deltas

    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == chapter_node_id).first()
        if not node:
            return json.dumps({"success": False, "error": "节点不存在"}, ensure_ascii=False)
        if node.type != "chapter":
            return json.dumps({"success": False, "error": "只能编辑章节节点"}, ensure_ascii=False)
        if not (node.content or "").strip():
            return json.dumps({
                "success": False,
                "error": "章节内容为空，无法编辑",
                "fallback_hint": "write_chapter",
            }, ensure_ascii=False)

        old_content = node.content
        global_nodes = get_global_nodes(db, work_id or node.work_id)
        global_context = format_global_context(global_nodes)
        prev_chapter = _read_prev_chapter_content(db, prev_chapter_node_id)
        elements = _collect_chapter_elements(db, chapter_node_id, work_id or node.work_id)

        llm = get_llm(temperature=0.3, streaming=True, **context_model_pref_kwargs())
        messages = _build_edit_chapter_messages(
            edit_instruction, old_content, context, global_context, prev_chapter, elements
        )

        emit = _get_emit()
        aggregated = None
        async for chunk in llm.astream(messages):
            aggregated = chunk if aggregated is None else aggregated + chunk
            if emit:
                await emit_llm_stream_deltas(emit, "chapter_edit_stream", chunk)

        resp = chunk_to_ai_message(aggregated) if aggregated is not None else None
        raw = getattr(resp, "content", "") if resp else ""
        if isinstance(raw, list):
            raw = "".join(b.get("text", "") for b in raw if isinstance(b, dict))

        try:
            parsed = _parse_edits_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            return json.dumps({
                "success": False,
                "error": f"无法解析 LLM 输出的 edits JSON: {e}",
                "fallback_hint": "write_chapter",
            }, ensure_ascii=False)

        edits = parsed["edits"]
        paragraphs = split_paragraphs(old_content)
        validation_errors = validate_edits(edits, paragraphs)
        if validation_errors:
            return json.dumps({
                "success": False,
                "error": validation_errors[0],
                "validation_errors": validation_errors,
                "fallback_hint": "write_chapter",
            }, ensure_ascii=False)

        try:
            new_content = apply_edits(old_content, edits)
        except ValueError as e:
            return json.dumps({
                "success": False,
                "error": str(e),
                "fallback_hint": "write_chapter",
            }, ensure_ascii=False)

        diff = build_chapter_edit_diff(old_content, new_content, edits)
        node.content = new_content
        clear_chapter_summary_on_content_change(db, node)
        db.commit()
        db.refresh(node)

        word_count = chapter_body_word_count(new_content)
        old_word_count = chapter_body_word_count(old_content)
        result = {
            "success": True,
            "chapter_node_id": chapter_node_id,
            "title": node.title,
            "word_count": word_count,
            "word_count_delta": word_count - old_word_count,
            "diff": diff,
        }

        if emit:
            await emit("chapter_edit_diff", {
                "chapter_node_id": chapter_node_id,
                "title": node.title,
                "word_count": word_count,
                "word_count_delta": word_count - old_word_count,
                "diff": diff,
            })
            await emit("nodes_updated", {"action": "edit_chapter", "chapter_node_id": chapter_node_id})

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _summarize_chapter_sync(chapter_node_id, reason=None):
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == chapter_node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        if node.type != "chapter":
            return json.dumps({"error": "只能总结章节节点"}, ensure_ascii=False)
        if not node.content:
            return json.dumps({"error": "章节内容为空"}, ensure_ascii=False)
        chapter = db.query(Chapter).filter(Chapter.node_id == chapter_node_id).first()
        return json.dumps({
            "success": True, "chapter_node_id": chapter_node_id, "title": node.title,
            "content": node.content, "existing_summary": chapter.summary if chapter else "",
            "instruction": "请生成章节摘要，并提取新增事实和伏笔",
        }, ensure_ascii=False)
    finally:
        db.close()


def _get_chapter_context_sync(chapter_node_id, reason=None):
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == chapter_node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        context = build_generation_context(db, chapter_node_id)
        return json.dumps({
            "success": True,
            "chapter": {"id": node.id, "title": node.title, "content": node.content},
            "context": context,
        }, ensure_ascii=False)
    finally:
        db.close()


def _check_chapter_consistency_sync(chapter_node_id, reason=None):
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == chapter_node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        if node.type != "chapter" or not node.content:
            return json.dumps({"error": "需要是已有内容的章节节点"}, ensure_ascii=False)
        context = build_generation_context(db, chapter_node_id)
        return json.dumps({
            "success": True, "chapter_node_id": chapter_node_id,
            "chapter_title": node.title, "chapter_content": node.content,
            "outline_nodes": context.get("outline_nodes", []),
            "character_nodes": context.get("character_nodes", []),
            "forbidden_reveals": context.get("forbidden_reveals", []),
            "instruction": "请检查章节内容与大纲、角色设定是否一致",
        }, ensure_ascii=False)
    finally:
        db.close()


# 异步包装
async def _create_chapter_under_micro_async(micro_node_id, title, relationship_type="main_plot", content="", reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_create_chapter_under_micro_sync, micro_node_id, title, relationship_type, content, reason))
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "create_chapter", "title": title})
    except Exception:
        logger.warning("_create_chapter_under_micro_async 触发 nodes_updated 失败", exc_info=True)
    return result


async def _generate_chapter_content_async(chapter_node_id, extra_instructions="", reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_generate_chapter_content_sync, chapter_node_id, extra_instructions, reason))
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "generate_chapter", "chapter_node_id": chapter_node_id})
    except Exception:
        logger.warning("_generate_chapter_content_async 触发 nodes_updated 失败", exc_info=True)
    return result


async def _edit_chapter_content_async(
    chapter_node_id,
    edit_instruction,
    context="",
    reason=None,
    prev_chapter_node_id=None,
    work_id=None,
):
    return await _edit_chapter_content_coroutine(
        chapter_node_id,
        edit_instruction,
        context,
        reason,
        work_id,
        prev_chapter_node_id,
    )


async def _summarize_chapter_async(chapter_node_id, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_summarize_chapter_sync, chapter_node_id, reason))


async def _get_chapter_context_async(chapter_node_id, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_get_chapter_context_sync, chapter_node_id, reason))


async def _check_chapter_consistency_async(chapter_node_id, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_check_chapter_consistency_sync, chapter_node_id, reason))


class WriteChapterInput(BaseModel):
    chapter_node_id: str = Field(description="章节节点ID")
    user_directive: str = Field(description="用户对本章的原始要求（原话，不准改写）")
    context: str = Field(description="写作上下文原文：必须是用查询工具备齐的真实素材（相关大纲、角色设定、伏笔的原文内容）。严禁写'写作要求/写作计划/本章要点/场景划分'等规划性文字。注：上一章正文不要放这里，由 prev_chapter_node_id 单独注入")
    extra: str = Field(default="", description="补充说明")
    prev_chapter_node_id: Optional[str] = Field(default=None, description="上一章的章节节点ID。工具会读取该节点正文注入提示词，保证本章承接上一章（人物状态/情节/伏笔连贯）。本章是开篇或无上一章时不传")
    work_id: Optional[str] = Field(default=None, description="作品ID（用于获取全局设定）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


_WRITE_CHAPTER_SYSTEM = """你是小说正文写手。根据给定的上下文与要求写出本章正文。

【铁律】
1. "用户对本章的原始要求"是用户原话，逐字遵守，禁止改写、扩写题材、增减用户明确指定的要素。
2. 仅在写作技巧层面（风格/视角/连贯/篇幅）发挥作用，不碰内容决策。
3. **只输出正文叙事本身**（具体的场景描写、人物动作、对话、心理活动），**严禁**输出任何形式的提纲、大纲、章节计划、场景划分、人物登场列表、伏笔清单、字数目标、写作思路等元结构或规划性内容。读者要看到的是故事本身，不是写作规划。
4. 即便"写作上下文"或"补充说明"中出现【写作要求】【场景划分】【人物登场】等结构化标签，也只把它们当作素材与约束，最终必须落笔成连贯的正文叙事，不得照搬或复述这些标签结构。

通用写作规范：第三人称叙事，视角统一，承接前文，本章篇幅约 2500-3500 字。"""


def _read_prev_chapter_content(db, prev_chapter_node_id) -> str:
    """读取上一章节点（agent 传入其 node_id）的正文；无 id 或节点不存在返回空串。"""
    if not prev_chapter_node_id:
        return ""
    n = db.query(Node).filter(Node.id == prev_chapter_node_id).first()
    if not n:
        return ""
    return n.content or ""


def _collect_chapter_elements(db, chapter_node_id, work_id) -> list:
    """查 chapter 的 contains 出边指向的 element 节点，返回 [{title, content}]。

    element 可跨章复用（一个 element 被多章 contains），这里只取本章关联的。
    """
    elements = (
        db.query(Node)
        .join(Edge, Edge.source_id == Node.id)
        .filter(
            Edge.target_id == chapter_node_id,
            Edge.edge_type.in_(("contains", "包含")),
            Edge.work_id == work_id,
            Node.type == "element",
        )
        .all()
    )
    return [{"title": e.title, "content": e.content or ""} for e in elements]


def _build_write_chapter_messages(
    user_directive,
    context,
    extra,
    global_context="",
    prev_chapter="",
    elements=None,
    chapter_title=None,
):
    system = _WRITE_CHAPTER_SYSTEM
    if global_context:
        system = global_context + "\n\n" + system
    sections = [
        "======= 用户对本章的原始要求（最高优先级，逐字遵守，禁止改写扩写）=======\n"
        f"{user_directive}\n"
        "=====================================================================",
    ]
    if chapter_title:
        sections.append(
            "======= 本章节点标题（唯一标题来源，正文中禁止重复输出）=======\n"
            f"{chapter_title}\n"
            "要求：章节标题由节点 title 统一管理。正文开头不要写 Markdown 标题，"
            "不要输出 # 章节名，也不要另起章节名。\n"
            "========================================================"
        )
    if prev_chapter:
        sections.append(
            "======= 上一章正文（承接前文，务必保持人物状态/情节/伏笔连贯，不得矛盾或重复）=======\n"
            f"{prev_chapter}\n"
            "====================================================================="
        )
    if elements:
        elem_text = "\n".join(f"- {e['title']}：{e['content']}" for e in elements)
        sections.append(
            "======= 本章情节元素（写正文时必须涵盖这些具体情节单元）=======\n"
            f"{elem_text}\n"
            "====================================================================="
        )
    sections.append(
        "======= 写作上下文（agent 已备齐，直接使用）=======\n"
        f"{context}\n"
        "================================================="
    )
    sections.append(
        "======= 本章补充说明（参考）=======\n"
        f"{extra}\n"
        "================================="
    )
    human = "\n\n".join(sections)
    return [SystemMessage(content=system), HumanMessage(content=human)]


def _strip_markdown_chapter_heading(content: str) -> str:
    """Node.title is the single title source; strip a generated leading Markdown H1."""
    if not content:
        return content

    match = re.match(r"^(\s*)#\s+(.+?)(\s*\n)", content)
    if not match:
        return content

    return content[match.end():].lstrip("\n")


async def _write_chapter_coroutine(chapter_node_id, user_directive, context, extra="", reason=None, work_id=None, prev_chapter_node_id=None) -> str:
    from app.services.agents.llm import get_llm, context_model_pref_kwargs
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == chapter_node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        # 禁止查库：context 由 agent 传入，工具内部不查数据库补充上下文
        # 获取全局上下文
        from app.services.global_context import get_global_nodes, format_global_context
        global_nodes = get_global_nodes(db, work_id or node.work_id)
        global_context = format_global_context(global_nodes)

        # 工具内部按 agent 传入的 prev_chapter_node_id 读取上一章正文，注入提示词保证连贯
        prev_chapter = _read_prev_chapter_content(db, prev_chapter_node_id)

        # 工具内部查本章关联的 element（contains 出边的 element 节点），注入提示词
        elements = _collect_chapter_elements(db, chapter_node_id, work_id or node.work_id)

        llm = get_llm(temperature=0.7, streaming=False, **context_model_pref_kwargs())
        messages = _build_write_chapter_messages(
            user_directive,
            context,
            extra,
            global_context,
            prev_chapter,
            elements,
            chapter_title=node.title,
        )
        resp = await llm.ainvoke(messages)
        content = getattr(resp, "content", str(resp))
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            )
        content = _strip_markdown_chapter_heading(content)
        node.content = content
        from app.services.chapter_history_service import clear_chapter_summary_on_content_change
        clear_chapter_summary_on_content_change(db, node)
        db.commit()
        db.refresh(node)
        neighbors = _neighbor_items(db, node.id, node.work_id)
        from app.services.chapter_word_count import chapter_body_word_count
        word_count = chapter_body_word_count(node.content or "")
        result_json = json.dumps({
            "success": True,
            "word_count": word_count,
            "node": {"id": node.id, "type": node.type, "title": node.title, "layer": node.layer, "content": node.content},
            "neighbors": neighbors,
        }, ensure_ascii=False)
        try:
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "write_chapter", "chapter_node_id": chapter_node_id})
        except Exception:
            logger.warning("_write_chapter_coroutine 触发 nodes_updated 失败", exc_info=True)
        return result_json
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


class EvaluateChapterInput(BaseModel):
    chapter_node_id: Optional[str] = Field(
        default=None,
        description="要评估的章节节点ID；省略则评估作品中按顺序最新且有正文的章节",
    )
    work_id: Optional[str] = Field(default=None, description="作品ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


def _parse_evaluate_chapter_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.strip().startswith("```")).strip()
    data = json.loads(text)
    if "evaluation" not in data or "chapter_overview" not in data:
        raise ValueError("模型返回缺少 evaluation 或 chapter_overview")
    return data


def _upsert_chapter_summary(db, node: Node, overview: str) -> None:
    chapter = db.query(Chapter).filter(Chapter.node_id == node.id).first()
    if not chapter:
        chapter = Chapter(
            work_id=node.work_id,
            node_id=node.id,
            title=node.title or "",
            content=node.content or "",
        )
        db.add(chapter)
    chapter.summary = overview


async def _evaluate_chapter_coroutine(
    chapter_node_id=None,
    reason=None,
    work_id=None,
) -> str:
    from app.services.chapter_history_service import (
        build_evaluate_chapter_messages,
        resolve_chapter_for_evaluation,
    )
    from app.services.agents.llm import get_llm

    db = _get_db()
    try:
        effective_work_id = work_id or _get_current_work_id()
        if not effective_work_id:
            return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

        chapter = resolve_chapter_for_evaluation(db, effective_work_id, chapter_node_id)
        if not chapter.content:
            return json.dumps({"error": "章节正文为空，无法评估"}, ensure_ascii=False)

        messages = build_evaluate_chapter_messages(db, effective_work_id, chapter)
        llm = get_llm(temperature=0.5, streaming=False)
        resp = await llm.ainvoke(messages)
        content = getattr(resp, "content", str(resp))
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        parsed = _parse_evaluate_chapter_response(content)
        _upsert_chapter_summary(db, chapter, parsed["chapter_overview"])
        db.commit()

        return json.dumps({
            "success": True,
            "chapter": {"id": chapter.id, "title": chapter.title},
            "evaluation": parsed["evaluation"],
            "chapter_overview": parsed["chapter_overview"],
        }, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except json.JSONDecodeError:
        return json.dumps({"error": "模型返回不是合法 JSON"}, ensure_ascii=False)
    except Exception as exc:
        db.rollback()
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


class CountChapterWordsInput(BaseModel):
    chapter_node_id: Optional[str] = Field(
        default=None,
        description="章节节点ID；省略则统计作品中按顺序最新且有正文的章节",
    )
    expected_word_count: Optional[int] = Field(
        default=None,
        description="期望字数；传入后会根据与实际字数的差异给出篇幅建议",
    )
    work_id: Optional[str] = Field(default=None, description="作品ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


async def _count_chapter_words_coroutine(
    chapter_node_id=None,
    expected_word_count=None,
    reason=None,
    work_id=None,
) -> str:
    from app.services.chapter_history_service import resolve_chapter_for_evaluation
    from app.services.chapter_word_count import build_word_count_advice, chapter_body_word_count

    db = _get_db()
    try:
        effective_work_id = work_id or _get_current_work_id()
        if not effective_work_id:
            return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

        if expected_word_count is not None and expected_word_count <= 0:
            return json.dumps({"error": "期望字数必须大于 0"}, ensure_ascii=False)

        chapter = resolve_chapter_for_evaluation(db, effective_work_id, chapter_node_id)
        word_count = chapter_body_word_count(chapter.content or "")

        payload = {
            "success": True,
            "chapter": {"id": chapter.id, "title": chapter.title},
            "word_count": word_count,
        }
        if expected_word_count is not None:
            payload["expected_word_count"] = expected_word_count
            payload["advice"] = build_word_count_advice(word_count, expected_word_count)

        return json.dumps(payload, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


# 创建工具
create_chapter_under_micro = StructuredTool.from_function(
    coroutine=_create_chapter_under_micro_async,
    func=_create_chapter_under_micro_sync,
    name="create_chapter_under_micro",
    description="在小纲节点下创建章节节点。章节是大纲的最底层，挂载在小纲下方。",
    args_schema=CreateChapterUnderMicroInput,
)

generate_chapter_content = StructuredTool.from_function(
    coroutine=_generate_chapter_content_async,
    func=_generate_chapter_content_sync,
    name="generate_chapter_content",
    description="根据连线的大纲、角色、风格节点生成章节内容",
    args_schema=GenerateChapterContentInput,
)

edit_chapter_content = StructuredTool.from_function(
    coroutine=_edit_chapter_content_async,
    name="edit_chapter_content",
    description=(
        "对已有正文做局部修改（改对话/措辞/删增少量段落）。"
        "章节为空或需大范围重写时用 write_chapter。"
        "工具内部注入全局设定与 prev_chapter_node_id 对应上一章正文。"
        "传入 edit_instruction（用户原话）与 context（agent 备齐素材）。"
        "校验失败时返回 fallback_hint=write_chapter，可改调 write_chapter。"
    ),
    args_schema=EditChapterContentInput,
)

summarize_chapter = StructuredTool.from_function(
    coroutine=_summarize_chapter_async,
    func=_summarize_chapter_sync,
    name="summarize_chapter",
    description="生成章节摘要，提取关键信息",
    args_schema=SummarizeChapterInput,
)

get_chapter_context = StructuredTool.from_function(
    coroutine=_get_chapter_context_async,
    func=_get_chapter_context_sync,
    name="get_chapter_context",
    description="获取章节的完整上下文信息",
    args_schema=GetChapterContextInput,
)

check_chapter_consistency = StructuredTool.from_function(
    coroutine=_check_chapter_consistency_async,
    func=_check_chapter_consistency_sync,
    name="check_chapter_consistency",
    description="检查章节与大纲的一致性",
    args_schema=CheckChapterConsistencyInput,
)


write_chapter = StructuredTool.from_function(
    coroutine=_write_chapter_coroutine,
    name="write_chapter",
    description=(
        "为章节节点生成正文。"
        "工具内部自动注入：全局设定(style/worldbuilding)、"
        "prev_chapter_node_id 对应上一章正文、本章 contains 的 element 列表。"
        "调用方传入 user_directive（用户原话）、"
        "context（用查询工具备齐的大纲/角色/伏笔原文，勿写规划性文字）、"
        "extra、prev_chapter_node_id（开篇章节不传）。"
        "篇幅目标约 2500–3500 字；返回 word_count 与正文。"
    ),
    args_schema=WriteChapterInput,
)

evaluate_chapter = StructuredTool.from_function(
    coroutine=_evaluate_chapter_coroutine,
    name="evaluate_chapter",
    description=(
        "以读者身份评估章节。system 注入角色设定；第一条 user 为前序章节"
        "（最近5章全文，更早章节用已存档概览）；第二条 user 为待评估章节全文。"
        "返回 evaluation（评估结果）与 chapter_overview（本章简短摘要，并写入章节摘要）。"
        "chapter_node_id 可省略，省略时评估最新有正文的章节。"
    ),
    args_schema=EvaluateChapterInput,
)

count_chapter_words = StructuredTool.from_function(
    coroutine=_count_chapter_words_coroutine,
    name="count_chapter_words",
    description=(
        "统计章节正文纯文字数（去除空格和换行）。"
        "可选 expected_word_count 对比期望字数并返回篇幅建议。"
        "chapter_node_id 可省略，省略时统计最新有正文的章节。"
    ),
    args_schema=CountChapterWordsInput,
)


# 导出章节工具
chapter_tools = [
    write_chapter,
    evaluate_chapter,
    count_chapter_words,
    create_chapter_under_micro,
    generate_chapter_content,
    edit_chapter_content,
    summarize_chapter,
    get_chapter_context,
    check_chapter_consistency,
]
