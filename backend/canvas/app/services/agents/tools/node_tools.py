"""节点操作工具"""
import json
import uuid
import asyncio
import logging
from typing import Optional
from functools import partial

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.node import Node
from app.models.edge import Edge

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


def _get_emit():
    """获取事件发射函数"""
    try:
        from app.services.agents.supervisor import get_context
        return get_context().get("emit")
    except:
        return None


# 节点类型由 agent 自由定义，不再枚举限制
VALID_NODE_TYPES = []  # 保留空列表以兼容旧代码引用


# 输入Schema
class CreateNodeInput(BaseModel):
    node_type: str = Field(description="节点类型")
    title: str = Field(description="节点标题")
    content: str = Field(default="", description="节点内容")
    layer: int = Field(default=0, description="垂直布局层级（整数，数字小的在上）")
    position_x: Optional[float] = Field(default=None, description="X坐标（可选，不传则自动计算）")
    position_y: Optional[float] = Field(default=None, description="Y坐标（可选，不传则自动计算）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class UpdateNodeInput(BaseModel):
    node_id: str = Field(description="节点ID")
    title: Optional[str] = Field(default=None, description="新标题")
    content: Optional[str] = Field(default=None, description="新内容")
    node_type: Optional[str] = Field(default=None, description="新类型")
    position_x: Optional[float] = Field(default=None, description="X坐标")
    position_y: Optional[float] = Field(default=None, description="Y坐标")
    manually_positioned: Optional[bool] = Field(default=None, description="是否手动拖拽定位")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class DeleteNodeInput(BaseModel):
    node_id: str = Field(description="节点ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class CreateEdgeInput(BaseModel):
    source_id: str = Field(description="源节点ID")
    target_id: str = Field(description="目标节点ID")
    edge_type: str = Field(default="uses", description="连线类型，用简短自然语言描述关系（如'包含'、'角色登场'、'伏笔埋设'、'场景关联'等，不超过100字符）")
    label: str = Field(default="", description="连线标签说明")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class DeleteEdgeInput(BaseModel):
    edge_id: str = Field(description="连线ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class UpdateEdgeInput(BaseModel):
    edge_id: str = Field(description="连线ID")
    edge_type: Optional[str] = Field(default=None, description="新的连线类型，短自然语言描述关系（不超过100字符）")
    label: Optional[str] = Field(default=None, description="新的连线标签")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class BatchCreateNodesInput(BaseModel):
    nodes_data: list[dict] = Field(description="节点数据列表")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class BatchCreateEdgesInput(BaseModel):
    edges_data: list[dict] = Field(description="连线数据列表")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


def _compact(node):
    """节点精简字段（不含正文），供邻居/索引返回。"""
    return {"id": node.id, "type": node.type, "title": node.title, "layer": node.layer, "manually_positioned": node.manually_positioned}


def _neighbor_items(db, node_id, work_id):
    """返回节点的一级邻居（双向 incoming/outgoing），精简字段 + 关系语义。"""
    neighbors = []
    seen = set()
    out_edges = db.query(Edge).filter(
        Edge.source_id == node_id, Edge.work_id == work_id
    ).all()
    in_edges = db.query(Edge).filter(
        Edge.target_id == node_id, Edge.work_id == work_id
    ).all()
    for e in out_edges:
        if e.target_id in seen:
            continue
        t = db.query(Node).filter(Node.id == e.target_id).first()
        if t:
            neighbors.append({"node": _compact(t), "edge": {"edge_type": e.edge_type, "direction": "out"}})
            seen.add(e.target_id)
    for e in in_edges:
        if e.source_id in seen:
            continue
        s = db.query(Node).filter(Node.id == e.source_id).first()
        if s:
            neighbors.append({"node": _compact(s), "edge": {"edge_type": e.edge_type, "direction": "in"}})
            seen.add(e.source_id)
    return neighbors


# 同步实现
def _create_node_sync(node_type, title, content="", layer=0, position_x=None, position_y=None, reason=None):
    if not node_type or not node_type.strip():
        return json.dumps({"error": "节点类型不能为空"}, ensure_ascii=False)
    
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
    
    db = _get_db()
    try:
        node = Node(
            id=str(uuid.uuid4()),
            work_id=work_id,
            type=node_type,
            title=title,
            content=content,
            layer=layer,
            position_x=position_x if position_x is not None else 0.0,
            position_y=position_y if position_y is not None else 0.0,
            manually_positioned=position_x is not None,
        )
        db.add(node)
        db.commit()
        db.refresh(node)
        return json.dumps({
            "success": True,
            "node": _compact(node),
            "neighbors": [],
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _update_node_sync(node_id, title=None, content=None, node_type=None, position_x=None, position_y=None, manually_positioned=None, reason=None):
    if node_type is not None and not node_type.strip():
        return json.dumps({"error": "节点类型不能为空"}, ensure_ascii=False)
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        if title is not None:
            node.title = title
        if content is not None:
            node.content = content
        if node_type is not None:
            node.type = node_type
        if position_x is not None:
            node.position_x = position_x
        if position_y is not None:
            node.position_y = position_y
        if manually_positioned is not None:
            node.manually_positioned = manually_positioned
        db.commit()
        db.refresh(node)
        neighbors = _neighbor_items(db, node.id, node.work_id)
        return json.dumps({
            "success": True,
            "node": _compact(node),
            "neighbors": neighbors,
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _delete_node_sync(node_id, reason=None):
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        work_id = node.work_id
        # 删前收集一级邻居（它们将失去与本节点的连接）
        neighbors = _neighbor_items(db, node_id, work_id)
        db.query(Edge).filter((Edge.source_id == node_id) | (Edge.target_id == node_id)).delete()
        db.delete(node)
        db.commit()
        return json.dumps({
            "success": True,
            "message": f"已删除节点: {node.title}",
            "neighbors": neighbors,
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _create_edge_sync(source_id, target_id, edge_type="uses", label="", reason=None):
    if len(edge_type) > 100:
        return json.dumps({"error": "连线类型不能超过100字符"}, ensure_ascii=False)
    if len(edge_type.strip()) == 0:
        return json.dumps({"error": "连线类型不能为空"}, ensure_ascii=False)
    
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
    
    db = _get_db()
    try:
        source = db.query(Node).filter(Node.id == source_id, Node.work_id == work_id).first()
        target = db.query(Node).filter(Node.id == target_id, Node.work_id == work_id).first()
        if not source:
            return json.dumps({"error": "源节点不存在"}, ensure_ascii=False)
        if not target:
            return json.dumps({"error": "目标节点不存在"}, ensure_ascii=False)
        existing = db.query(Edge).filter(
            Edge.source_id == source_id, Edge.target_id == target_id, Edge.edge_type == edge_type
        ).first()
        if existing:
            return json.dumps({"error": "该连线已存在"}, ensure_ascii=False)
        edge = Edge(
            id=str(uuid.uuid4()),
            work_id=work_id,
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            label=label
        )
        db.add(edge)
        db.commit()
        db.refresh(edge)
        neighbors = [
            {"node": _compact(target), "edge": {"edge_type": edge_type, "direction": "out"}},
            {"node": _compact(source), "edge": {"edge_type": edge_type, "direction": "in"}},
        ]
        return json.dumps({
            "success": True,
            "edge": {"id": edge.id, "source_id": source_id, "source_title": source.title, "target_id": target_id, "target_title": target.title, "edge_type": edge_type, "label": label},
            "neighbors": neighbors,
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _delete_edge_sync(edge_id, reason=None):
    db = _get_db()
    try:
        edge = db.query(Edge).filter(Edge.id == edge_id).first()
        if not edge:
            return json.dumps({"error": "连线不存在"}, ensure_ascii=False)
        # 删前拿端点（它们将失去这条连接）
        endpoints = []
        for nid in (edge.source_id, edge.target_id):
            n = db.query(Node).filter(Node.id == nid).first()
            if n:
                endpoints.append(_compact(n))
        db.delete(edge)
        db.commit()
        return json.dumps({
            "success": True,
            "message": "已删除连线",
            "neighbors": endpoints,
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _update_edge_sync(edge_id, edge_type=None, label=None, reason=None):
    db = _get_db()
    try:
        edge = db.query(Edge).filter(Edge.id == edge_id).first()
        if not edge:
            return json.dumps({"error": "连线不存在"}, ensure_ascii=False)
        if edge_type is not None:
            if len(edge_type) > 100 or len(edge_type.strip()) == 0:
                return json.dumps({"error": "连线类型不能为空且不超过100字符"}, ensure_ascii=False)
            edge.edge_type = edge_type
        if label is not None:
            edge.label = label
        db.commit()
        db.refresh(edge)
        endpoints = []
        for nid in (edge.source_id, edge.target_id):
            n = db.query(Node).filter(Node.id == nid).first()
            if n:
                endpoints.append(_compact(n))
        return json.dumps({
            "success": True,
            "edge": {"id": edge.id, "source_id": edge.source_id, "target_id": edge.target_id, "edge_type": edge.edge_type, "label": edge.label},
            "neighbors": endpoints,
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _batch_create_nodes_sync(nodes_data, reason=None):
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
    
    db = _get_db()
    try:
        created_nodes = []
        for data in nodes_data:
            node_type = data.get("node_type") or data.get("type", "idea")
            if not node_type or not node_type.strip():
                continue
            layer = data.get("layer", 0)
            position_x = data.get("position_x")
            position_y = data.get("position_y")
            node = Node(
                id=str(uuid.uuid4()),
                work_id=work_id,
                type=node_type,
                title=data.get("title", "未命名"),
                content=data.get("content", ""),
                layer=layer,
                position_x=position_x if position_x is not None else 0.0,
                position_y=position_y if position_y is not None else 0.0,
                manually_positioned=position_x is not None,
            )
            db.add(node)
            created_nodes.append(node)
        
        db.commit()
        for node in created_nodes:
            db.refresh(node)
        return json.dumps({
            "success": True,
            "nodes": [_compact(n) for n in created_nodes],
            "neighbors": [],
            "count": len(created_nodes),
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _batch_create_edges_sync(edges_data, reason=None):
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
    
    db = _get_db()
    try:
        created_edges = []
        for data in edges_data:
            source_id = data.get("source_id")
            target_id = data.get("target_id")
            edge_type = data.get("edge_type", "uses")
            if not source_id or not target_id:
                continue
            if len(edge_type) > 100 or len(edge_type.strip()) == 0:
                continue
            source = db.query(Node).filter(Node.id == source_id, Node.work_id == work_id).first()
            target = db.query(Node).filter(Node.id == target_id, Node.work_id == work_id).first()
            if not source or not target:
                continue
            edge = Edge(
                id=str(uuid.uuid4()),
                work_id=work_id,
                source_id=source_id,
                target_id=target_id,
                edge_type=edge_type,
                label=data.get("label", ""),
            )
            db.add(edge)
            created_edges.append(edge)
        db.commit()
        for edge in created_edges:
            db.refresh(edge)
        endpoint_ids = []
        seen = set()
        for e in created_edges:
            for nid in (e.source_id, e.target_id):
                if nid not in seen:
                    seen.add(nid)
                    n = db.query(Node).filter(Node.id == nid).first()
                    if n:
                        endpoint_ids.append(_compact(n))
        return json.dumps({
            "success": True,
            "edges": [{"id": e.id, "source_id": e.source_id, "target_id": e.target_id, "edge_type": e.edge_type} for e in created_edges],
            "neighbors": endpoint_ids,
            "count": len(created_edges),
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


# 异步包装
async def _create_node_async(node_type, title, content="", layer=0, position_x=None, position_y=None, reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_create_node_sync, node_type, title, content, layer, position_x, position_y, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "create", "node_type": node_type})
    except:
        pass
    return result


async def _update_node_async(node_id, title=None, content=None, node_type=None, position_x=None, position_y=None, manually_positioned=None, reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_update_node_sync, node_id, title, content, node_type, position_x, position_y, manually_positioned, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "update", "node_id": node_id})
    except:
        pass
    return result


async def _delete_node_async(node_id, reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_delete_node_sync, node_id, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "delete", "node_id": node_id})
    except:
        pass
    return result


async def _create_edge_async(source_id, target_id, edge_type="uses", label="", reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_create_edge_sync, source_id, target_id, edge_type, label, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "edge_create", "edge_type": edge_type})
    except:
        pass
    return result


async def _delete_edge_async(edge_id, reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_delete_edge_sync, edge_id, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "edge_delete", "edge_id": edge_id})
    except:
        pass


async def _update_edge_async(edge_id, edge_type=None, label=None, reason=None):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, partial(_update_edge_sync, edge_id, edge_type, label, reason)
    )
    return result


async def _batch_create_nodes_async(nodes_data, reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_batch_create_nodes_sync, nodes_data, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "batch_create", "count": data.get("count", 0)})
    except:
        pass
    return result


async def _batch_create_edges_async(edges_data, reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_batch_create_edges_sync, edges_data, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "batch_edge_create", "count": data.get("count", 0)})
    except:
        pass
    return result


# 创建工具
create_node = StructuredTool.from_function(
    coroutine=_create_node_async,
    func=_create_node_sync,
    name="create_node",
    description="创建新节点。会自动计算位置，新节点出现在画布最右侧。",
    args_schema=CreateNodeInput,
)

update_node = StructuredTool.from_function(
    coroutine=_update_node_async,
    func=_update_node_sync,
    name="update_node",
    description="更新节点的任意属性，包括标题、内容、类型、坐标和层级。可用于调整布局（position_x/y）或重新分类（node_type）。",
    args_schema=UpdateNodeInput,
)

delete_node = StructuredTool.from_function(
    coroutine=_delete_node_async,
    func=_delete_node_sync,
    name="delete_node",
    description="删除指定节点及其所有连线。",
    args_schema=DeleteNodeInput,
)

create_edge = StructuredTool.from_function(
    coroutine=_create_edge_async,
    func=_create_edge_sync,
    name="create_edge",
    description="在两个节点之间创建连线。",
    args_schema=CreateEdgeInput,
)

delete_edge = StructuredTool.from_function(
    coroutine=_delete_edge_async,
    func=_delete_edge_sync,
    name="delete_edge",
    description="删除指定连线。",
    args_schema=DeleteEdgeInput,
)

update_edge = StructuredTool.from_function(
    coroutine=_update_edge_async,
    func=_update_edge_sync,
    name="update_edge",
    description="更新连线的类型或标签。不改变起止点。",
    args_schema=UpdateEdgeInput,
)

batch_create_nodes = StructuredTool.from_function(
    coroutine=_batch_create_nodes_async,
    func=_batch_create_nodes_sync,
    name="batch_create_nodes",
    description="批量创建多个节点。",
    args_schema=BatchCreateNodesInput,
)

batch_create_edges = StructuredTool.from_function(
    coroutine=_batch_create_edges_async,
    func=_batch_create_edges_sync,
    name="batch_create_edges",
    description="批量创建多个连线。",
    args_schema=BatchCreateEdgesInput,
)


# 导出所有节点操作工具
node_tools = [
    create_node,
    update_node,
    delete_node,
    create_edge,
    delete_edge,
    update_edge,
    batch_create_nodes,
    batch_create_edges,
]
