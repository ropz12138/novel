"""章节工具 - 生成和编辑章节"""
import json
import asyncio
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
from app.services.agents.tools.node_tools import _compact, _neighbor_items


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
    edit_instruction: str = Field(description="编辑指令")
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


def _edit_chapter_content_sync(chapter_node_id, edit_instruction, reason=None):
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == chapter_node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        if node.type != "chapter":
            return json.dumps({"error": "只能编辑章节节点"}, ensure_ascii=False)
        if not node.content:
            return json.dumps({"error": "章节内容为空，无法编辑"}, ensure_ascii=False)
        return json.dumps({
            "success": True, "chapter_node_id": chapter_node_id,
            "current_content": node.content, "edit_instruction": edit_instruction,
            "instruction": "请根据编辑指令修改章节内容",
        }, ensure_ascii=False)
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
    return await loop.run_in_executor(None, partial(_create_chapter_under_micro_sync, micro_node_id, title, relationship_type, content, reason))


async def _generate_chapter_content_async(chapter_node_id, extra_instructions="", reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_generate_chapter_content_sync, chapter_node_id, extra_instructions, reason))


async def _edit_chapter_content_async(chapter_node_id, edit_instruction, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_edit_chapter_content_sync, chapter_node_id, edit_instruction, reason))


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
    context: str = Field(description="agent 用查询工具备齐的写作上下文（大纲/前文/角色/伏笔）")
    extra: str = Field(default="", description="补充说明")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


_WRITE_CHAPTER_SYSTEM = """你是小说正文写手。根据给定的上下文与要求写出本章正文。

【铁律】
1. "用户对本章的原始要求"是用户原话，逐字遵守，禁止改写、扩写题材、增减用户明确指定的要素。
2. 仅在写作技巧层面（风格/视角/连贯/篇幅）发挥作用，不碰内容决策。

通用写作规范：第三人称叙事，视角统一，承接前文，本章篇幅约 2000-3500 字。"""


def _build_write_chapter_messages(user_directive, context, extra):
    human = (
        "======= 用户对本章的原始要求（最高优先级，逐字遵守，禁止改写扩写）=======\n"
        f"{user_directive}\n"
        "=====================================================================\n\n"
        "======= 写作上下文（agent 已备齐，直接使用）=======\n"
        f"{context}\n"
        "=================================================\n\n"
        "======= 本章补充说明（参考）=======\n"
        f"{extra}\n"
        "================================="
    )
    return [SystemMessage(content=_WRITE_CHAPTER_SYSTEM), HumanMessage(content=human)]


async def _write_chapter_coroutine(chapter_node_id, user_directive, context, extra="", reason=None) -> str:
    from app.services.agents.llm import get_llm
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == chapter_node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        # 禁止查库：context 由 agent 传入，工具内部不查数据库补充上下文
        llm = get_llm(temperature=0.7, streaming=False)
        messages = _build_write_chapter_messages(user_directive, context, extra)
        resp = await llm.ainvoke(messages)
        content = getattr(resp, "content", str(resp))
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") for b in content if isinstance(b, dict)
            )
        node.content = content
        db.commit()
        db.refresh(node)
        neighbors = _neighbor_items(db, node.id, node.work_id)
        return json.dumps({
            "success": True,
            "node": {"id": node.id, "type": node.type, "title": node.title, "layer": node.layer, "content": node.content},
            "neighbors": neighbors,
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
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
    func=_edit_chapter_content_sync,
    name="edit_chapter_content",
    description="根据指令编辑已有章节内容",
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
    description="为章节节点生成正文。入参：chapter_node_id、user_directive（用户原话）、context（agent 备齐的写作上下文）、extra（补充）。工具内部不查库，上下文必须由调用方传入。返回章节节点（含正文）+ 一级邻居。",
    args_schema=WriteChapterInput,
)


# 导出章节工具
chapter_tools = [
    write_chapter,
    create_chapter_under_micro,
    generate_chapter_content,
    edit_chapter_content,
    summarize_chapter,
    get_chapter_context,
    check_chapter_consistency,
]
