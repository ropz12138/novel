"""查询工具 - 结构化查询和grep查询"""
import json
import asyncio
from typing import Optional
from functools import partial

from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel, Field

from app.models.node import Node
from app.models.edge import Edge
from app.models.chapter import Chapter


def _get_db():
    """获取数据库会话（工具内部使用）"""
    from app.database import SessionLocal
    return SessionLocal()


def _get_current_work_id():
    """获取当前work_id"""
    try:
        from app.services.agents.supervisor import get_context
        return get_context().get("work_id")
    except:
        return None


# 定义输入Schema
class QueryNodesInput(BaseModel):
    node_type: Optional[str] = Field(default=None, description="节点类型过滤")
    keyword: Optional[str] = Field(default=None, description="标题或内容中的关键词")
    limit: int = Field(default=50, description="返回数量限制")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class QueryEdgesInput(BaseModel):
    source_id: Optional[str] = Field(default=None, description="源节点ID")
    target_id: Optional[str] = Field(default=None, description="目标节点ID")
    edge_type: Optional[str] = Field(default=None, description="连线类型")
    limit: int = Field(default=100, description="返回数量限制")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class ReadNodeContentInput(BaseModel):
    node_ids: list[str] = Field(description="节点ID列表，支持批量查询")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class GrepNodesInput(BaseModel):
    keywords: list[str] = Field(description="关键词列表")
    node_type: Optional[str] = Field(default=None, description="限制搜索的节点类型")
    context_chars: int = Field(default=100, description="匹配位置前后的上下文字符数")
    limit: int = Field(default=20, description="返回结果数量限制")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


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
                "content_preview": node.content[:200] if node.content else "",
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
        nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
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
                "extra_data": node.extra_data,
                "outgoing_edges": outgoing,
                "incoming_edges": incoming,
            })
        
        return json.dumps({"nodes": results, "total": len(results)}, ensure_ascii=False)
    finally:
        db.close()


def _grep_nodes_sync(keywords, node_type=None, context_chars=100, limit=20, reason=None):
    db = _get_db()
    try:
        work_id = _get_current_work_id()
        query = db.query(Node)
        if work_id:
            query = query.filter(Node.work_id == work_id)
        if node_type:
            query = query.filter(Node.type == node_type)
        nodes = query.all()
        results = []
        for node in nodes:
            content = f"{node.title} {node.content}"
            for keyword in keywords:
                if keyword.lower() in content.lower():
                    idx = content.lower().find(keyword.lower())
                    start = max(0, idx - context_chars)
                    end = min(len(content), idx + len(keyword) + context_chars)
                    context = content[start:end]
                    results.append({
                        "node_id": node.id,
                        "node_type": node.type,
                        "title": node.title,
                        "keyword": keyword,
                        "context": f"...{context}...",
                    })
                    break
            if len(results) >= limit:
                break
        return json.dumps({"matches": results, "total": len(results)}, ensure_ascii=False)
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
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_query_nodes_sync, node_type, keyword, limit, reason))


async def _query_edges_async(source_id=None, target_id=None, edge_type=None, limit=100, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_query_edges_sync, source_id, target_id, edge_type, limit, reason))


async def _read_node_content_async(node_ids: list[str], reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_read_node_content_sync, node_ids, reason))


async def _grep_nodes_async(keywords, node_type=None, context_chars=100, limit=20, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_grep_nodes_sync, keywords, node_type, context_chars, limit, reason))


async def _get_canvas_overview_async(work_id=None, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_get_canvas_overview_sync, work_id, reason))


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
    description="读取指定节点的完整内容，支持批量查询多个节点。",
    args_schema=ReadNodeContentInput,
)

grep_nodes = StructuredTool.from_function(
    coroutine=_grep_nodes_async,
    func=_grep_nodes_sync,
    name="grep_nodes",
    description="在节点内容中搜索关键词，返回匹配的上下文。",
    args_schema=GrepNodesInput,
)

get_canvas_overview = StructuredTool.from_function(
    coroutine=_get_canvas_overview_async,
    func=_get_canvas_overview_sync,
    name="get_canvas_overview",
    description="获取画布概览，包括各类型节点数量和连线统计。",
    args_schema=CanvasOverviewInput,
)


# 导出所有查询工具
query_tools = [
    query_nodes,
    query_edges,
    read_node_content,
    grep_nodes,
    get_canvas_overview,
]
