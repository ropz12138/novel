"""查询工具 - 结构化查询和grep查询"""
import json
import hashlib
import asyncio
from typing import Literal, Optional
from functools import partial

from langchain_core.tools import StructuredTool
from sqlalchemy import or_
from pydantic import BaseModel, Field, model_validator

from models.node import Node
from models.edge import Edge
from models.chapter import Chapter


def _get_db():
    """获取数据库会话（工具内部使用）"""
    from database import SessionLocal
    return SessionLocal()


def _get_current_work_id():
    """获取当前work_id"""
    try:
        from services.agents.supervisor import get_context
        return get_context().get("work_id")
    except:
        return None


# 定义输入Schema
class QueryNodesInput(BaseModel):
    node_type: Optional[str] = Field(default=None, description="节点类型过滤")
    keyword: Optional[str] = Field(default=None, description="标题或内容中的关键词")
    limit: int = Field(default=50, ge=1, le=50, description="返回数量限制")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class QueryEdgesInput(BaseModel):
    source_id: Optional[str] = Field(default=None, description="源节点ID")
    target_id: Optional[str] = Field(default=None, description="目标节点ID")
    edge_type: Optional[str] = Field(default=None, description="连线类型")
    limit: int = Field(default=50, ge=1, le=50, description="返回数量限制")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class ReadNodeContentInput(BaseModel):
    node_ids: list[str] = Field(min_length=1, max_length=5,
        description=(
            "节点 ID 列表（UUID），须来自 get_canvas_index，一次性传入所有需读 ID。"
            "禁止用标题当 ID，禁止连续多次单节点读取。"
        ),
    )
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class GrepNodesInput(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=10, description="关键词列表")
    node_type: Optional[str] = Field(default=None, description="限制搜索的节点类型")
    fields: list[Literal["title", "content", "notes", "extra_data.chapter_elements",
                         "extra_data.characters", "extra_data.storylines"]] = Field(
        default_factory=lambda: ["title", "content", "notes"], min_length=1)
    match_mode: Literal["any", "all"] = "any"
    limit: int = Field(default=20, ge=1, le=50, description="返回结果数量限制")
    offset: int = Field(default=0, ge=0)
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")

    @model_validator(mode="after")
    def validate_search(self):
        if any(not word.strip() for word in self.keywords) or len(set(self.keywords)) != len(self.keywords):
            raise ValueError("关键词必须非空且不能重复")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("搜索字段不能重复")
        return self


class CanvasOverviewInput(BaseModel):
    work_id: Optional[str] = Field(default=None, description="作品ID（可选）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


# 同步实现
def _query_nodes_sync(node_type=None, keyword=None, limit=50, reason=None):
    db = _get_db()
    try:
        work_id = _get_current_work_id()
        query = db.query(Node)
        if work_id:
            query = query.filter(Node.work_id == work_id)
        if node_type:
            query = query.filter(Node.type == node_type)
        if keyword:
            keyword_pattern = f"%{keyword}%"
            query = query.filter(
                or_(
                    Node.title.ilike(keyword_pattern),
                    Node.content.ilike(keyword_pattern),
                )
            )
        nodes = query.limit(limit).all()
        result = []
        for node in nodes:
            result.append({
                "id": node.id,
                "type": node.type,
                "title": node.title,
                "has_content": bool(node.content),
                "created_at": node.created_at.isoformat() if node.created_at else None,
            })
        return json.dumps({"nodes": result, "total": len(result)}, ensure_ascii=False)
    finally:
        db.close()


def _query_edges_sync(source_id=None, target_id=None, edge_type=None, limit=100, reason=None):
    db = _get_db()
    try:
        work_id = _get_current_work_id()
        query = db.query(Edge)
        if work_id:
            query = query.filter(Edge.work_id == work_id)
        if source_id:
            query = query.filter(Edge.source_id == source_id)
        if target_id:
            query = query.filter(Edge.target_id == target_id)
        if edge_type:
            query = query.filter(Edge.edge_type == edge_type)
        edges = query.limit(limit).all()
        result = []
        for edge in edges:
            source_node = db.query(Node).filter(Node.id == edge.source_id).first()
            target_node = db.query(Node).filter(Node.id == edge.target_id).first()
            result.append({
                "id": edge.id,
                "source_id": edge.source_id,
                "source_title": source_node.title if source_node else "未知",
                "target_id": edge.target_id,
                "target_title": target_node.title if target_node else "未知",
                "edge_type": edge.edge_type,
                "label": edge.label,
            })
        return json.dumps({"edges": result, "total": len(result)}, ensure_ascii=False)
    finally:
        db.close()


def _read_node_content_sync(node_ids: list[str], reason=None):
    db = _get_db()
    try:
        query = db.query(Node).filter(Node.id.in_(node_ids))
        work_id = _get_current_work_id()
        if work_id:
            query = query.filter(Node.work_id == work_id)
        nodes = query.all()
        if not nodes:
            return json.dumps({"error": "未找到节点"}, ensure_ascii=False)
        
        results = []
        for node in nodes:
            outgoing_edges = db.query(Edge).filter(Edge.source_id == node.id).all()
            incoming_edges = db.query(Edge).filter(Edge.target_id == node.id).all()
            outgoing = []
            for edge in outgoing_edges:
                target = db.query(Node).filter(Node.id == edge.target_id).first()
                outgoing.append({
                    "target_id": edge.target_id,
                    "target_title": target.title if target else "未知",
                    "edge_type": edge.edge_type,
                })
            incoming = []
            for edge in incoming_edges:
                source = db.query(Node).filter(Node.id == edge.source_id).first()
                incoming.append({
                    "source_id": edge.source_id,
                    "source_title": source.title if source else "未知",
                    "edge_type": edge.edge_type,
                })
            results.append({
                "id": node.id,
                "type": node.type,
                "title": node.title,
                "content": node.content,
                "content_sha256": hashlib.sha256((node.content or "").encode("utf-8")).hexdigest(),
                "extra_data": node.extra_data,
                "outgoing_edges": outgoing,
                "incoming_edges": incoming,
            })
            if node.type == "chapter":
                chapter = db.query(Chapter).filter_by(node_id=node.id).first()
                results[-1]["notes"] = chapter.notes if chapter else ""
        
        return json.dumps({"nodes": results, "total": len(results)}, ensure_ascii=False)
    finally:
        db.close()


def _text_leaves(value, path):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _text_leaves(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _text_leaves(item, f"{path}.{key}")


def _grep_nodes_sync(keywords, node_type=None, fields=None, match_mode="any", limit=20, offset=0, reason=None):
    db = _get_db()
    try:
        work_id = _get_current_work_id()
        if not work_id:
            return json.dumps({"success": False, "error": "当前会话未绑定作品"}, ensure_ascii=False)
        query = db.query(Node)
        query = query.filter(Node.work_id == work_id)
        if node_type:
            query = query.filter(Node.type == node_type)
        nodes = query.order_by(Node.sort_order, Node.id).all()
        requested_fields = fields or ["title", "content", "notes"]
        chapter_ids = [node.id for node in nodes if node.type == "chapter"]
        notes_by_node = {row.node_id: row.notes or "" for row in db.query(Chapter).filter(Chapter.node_id.in_(chapter_ids)).all()} if chapter_ids else {}
        results = []
        for node in nodes:
            searchable = []
            for field in requested_fields:
                if field == "title":
                    searchable.append((field, node.title or ""))
                elif field == "content":
                    searchable.append((field, node.content or ""))
                elif field == "notes":
                    searchable.append((field, notes_by_node.get(node.id, "")))
                else:
                    key = field.removeprefix("extra_data.")
                    searchable.extend(_text_leaves((node.extra_data or {}).get(key), field))
            found_words = {
                keyword for keyword in keywords
                if any(keyword.casefold() in text.casefold() for _, text in searchable)
            }
            if (match_mode == "all" and len(found_words) != len(keywords)) or (match_mode == "any" and not found_words):
                continue
            for field_path, text in searchable:
                lower = text.casefold()
                for keyword in keywords:
                    idx = lower.find(keyword.casefold())
                    if idx < 0:
                        continue
                    results.append({
                        "node_id": node.id,
                        "node_type": node.type,
                        "title": node.title,
                        "keyword": keyword,
                        "field_path": field_path,
                        "match_start": idx,
                        "match_end": idx + len(keyword),
                        "field_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    })
        page = results[offset:offset + limit]
        return json.dumps({"success": True, "matches": page, "total": len(page),
                           "has_more": offset + len(page) < len(results),
                           "next_offset": offset + len(page)}, ensure_ascii=False)
    finally:
        db.close()


def _get_canvas_overview_sync(work_id=None, reason=None):
    db = _get_db()
    try:
        if not work_id:
            work_id = _get_current_work_id()
        
        query = db.query(Node)
        if work_id:
            query = query.filter(Node.work_id == work_id)
        nodes = query.all()
        
        node_stats = {}
        for node in nodes:
            node_stats[node.type] = node_stats.get(node.type, 0) + 1
        
        edge_query = db.query(Edge)
        if work_id:
            edge_query = edge_query.filter(Edge.work_id == work_id)
        edges = edge_query.all()
        
        edge_stats = {}
        for edge in edges:
            edge_stats[edge.edge_type] = edge_stats.get(edge.edge_type, 0) + 1
        
        chapters = [n for n in nodes if n.type == "chapter"]
        chapter_list = []
        for ch in chapters:
            chapter_list.append({
                "id": ch.id,
                "title": ch.title,
                "has_content": bool(ch.content),
            })
        
        return json.dumps({
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "node_stats": node_stats,
            "edge_stats": edge_stats,
            "chapters": chapter_list,
        }, ensure_ascii=False)
    finally:
        db.close()


# 异步包装
async def _query_nodes_async(node_type=None, keyword=None, limit=50, reason=None):
    return await asyncio.to_thread(partial(_query_nodes_sync, node_type, keyword, limit, reason))


async def _query_edges_async(source_id=None, target_id=None, edge_type=None, limit=100, reason=None):
    return await asyncio.to_thread(partial(_query_edges_sync, source_id, target_id, edge_type, limit, reason))


async def _read_node_content_async(node_ids: list[str], reason=None):
    return await asyncio.to_thread(partial(_read_node_content_sync, node_ids, reason))


async def _grep_nodes_async(keywords, node_type=None, fields=None, match_mode="any", limit=20, offset=0, reason=None):
    return await asyncio.to_thread(partial(_grep_nodes_sync, keywords, node_type, fields, match_mode, limit, offset, reason))


async def _get_canvas_overview_async(work_id=None, reason=None):
    return await asyncio.to_thread(partial(_get_canvas_overview_sync, work_id, reason))


# 创建工具
query_nodes = StructuredTool.from_function(
    coroutine=_query_nodes_async,
    func=_query_nodes_sync,
    name="query_nodes",
    description="查询节点列表。可以按类型和关键词过滤。",
    args_schema=QueryNodesInput,
)

query_edges = StructuredTool.from_function(
    coroutine=_query_edges_async,
    func=_query_edges_sync,
    name="query_edges",
    description="查询连线关系。可以按源节点、目标节点或连线类型过滤。",
    args_schema=QueryEdgesInput,
)

read_node_content = StructuredTool.from_function(
    coroutine=_read_node_content_async,
    func=_read_node_content_sync,
    name="read_node_content",
    description=(
        "批量读取节点完整正文。先 get_canvas_index 获取 UUID，再一次性传入 node_ids 列表。"
    ),
    args_schema=ReadNodeContentInput,
)

grep_nodes = StructuredTool.from_function(
    coroutine=_grep_nodes_async,
    func=_grep_nodes_sync,
    name="grep_nodes",
    description="在节点标题、正文、章节笔记或声明的元数据字段中定位关键词；返回字段路径和位置，不返回字段全文。",
    args_schema=GrepNodesInput,
)

get_canvas_overview = StructuredTool.from_function(
    coroutine=_get_canvas_overview_async,
    func=_get_canvas_overview_sync,
    name="get_canvas_overview",
    description="获取画布概览，包括各类型节点数量和连线统计。",
    args_schema=CanvasOverviewInput,
)


class CanvasIndexInput(BaseModel):
    node_offset: int = Field(default=0, ge=0, description="节点分页偏移")
    node_limit: int = Field(default=50, ge=1, le=50, description="本页节点数")
    edge_offset: int = Field(default=0, ge=0, description="连线分页偏移")
    edge_limit: int = Field(default=50, ge=1, le=50, description="本页连线数")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class ListUserCanvasActionsInput(BaseModel):
    limit: int = Field(default=50, ge=1, le=50, description="返回数量限制，按时间倒序（最新在前）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


def _get_canvas_index_sync(node_offset=0, node_limit=50, edge_offset=0, edge_limit=50, reason=None):
    db = _get_db()
    try:
        work_id = _get_current_work_id()
        node_q = db.query(Node)
        if work_id:
            node_q = node_q.filter(Node.work_id == work_id)
        total_nodes = node_q.count()
        nodes = node_q.order_by(Node.sort_order, Node.id).offset(node_offset).limit(node_limit).all()
        node_items = [
            {"id": n.id, "type": n.type, "title": n.title, "layer": n.layer}
            for n in nodes
        ]

        edge_q = db.query(Edge)
        if work_id:
            edge_q = edge_q.filter(Edge.work_id == work_id)
        total_edges = edge_q.count()
        edges = edge_q.order_by(Edge.id).offset(edge_offset).limit(edge_limit).all()
        edge_items = [
            {"source_id": e.source_id, "target_id": e.target_id, "edge_type": e.edge_type}
            for e in edges
        ]

        return json.dumps({
            "nodes": node_items,
            "edges": edge_items,
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "node_offset": node_offset,
            "edge_offset": edge_offset,
            "has_more_nodes": node_offset + len(node_items) < total_nodes,
            "has_more_edges": edge_offset + len(edge_items) < total_edges,
        }, ensure_ascii=False)
    finally:
        db.close()


async def _get_canvas_index_async(node_offset=0, node_limit=50, edge_offset=0, edge_limit=50, reason=None):
    return await asyncio.to_thread(partial(
        _get_canvas_index_sync, node_offset, node_limit, edge_offset, edge_limit, reason,
    ))


get_canvas_index = StructuredTool.from_function(
    coroutine=_get_canvas_index_async,
    func=_get_canvas_index_sync,
    name="get_canvas_index",
    description=(
        "分页获取画布精简目录（id/type/title/layer + 边关系，不含正文）。"
        "查节点前先调用本工具，再用 read_node_content(node_ids=[...]) 批量读详情。"
        "禁止用标题当 ID。"
    ),
    args_schema=CanvasIndexInput,
)




def _list_user_canvas_actions_sync(limit=50, reason=None):
    from services import user_action_service

    work_id = _get_current_work_id()
    db = _get_db()
    try:
        actions = user_action_service.list_actions(db, work_id, limit=limit)
    finally:
        db.close()
    if not actions:
        return json.dumps({"actions": [], "message": "暂无用户画布操作记录"}, ensure_ascii=False)
    return json.dumps({"actions": actions, "total": len(actions)}, ensure_ascii=False)


async def _list_user_canvas_actions_async(limit=50, reason=None):
    return await asyncio.to_thread(partial(_list_user_canvas_actions_sync, limit, reason))


list_user_canvas_actions = StructuredTool.from_function(
    coroutine=_list_user_canvas_actions_async,
    func=_list_user_canvas_actions_sync,
    name="list_user_canvas_actions",
    description=(
        "列出用户在画布上最近的操作记录（用户手动增删改节点/边，不含你自己的工具操作）。"
        "节点操作只提供操作类型和节点标题，不提供节点内容；连线创建/删除操作可能附带关系摘要。"
        "按时间倒序（最新在前）。"
    ),
    args_schema=ListUserCanvasActionsInput,
)


# 导出所有查询工具
from .node_reference_tools import create_node_references

query_tools = [
    create_node_references,
    query_nodes,
    query_edges,
    read_node_content,
    grep_nodes,
    get_canvas_overview,
    get_canvas_index,
    list_user_canvas_actions,
]
