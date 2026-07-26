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
from app.services.edge_layout_service import build_edge_layout
from app.services.agents.node_layout import node_rect, detect_rect_issue, detect_edge_overlap
from app.node_types import (
    STANDARD_NODE_TYPES,
    NODE_TYPES_RULES_TEXT,
    NODE_LAYOUT_RULES_TEXT,
    EDGE_ENDPOINT_RULES_TEXT,
    EDGE_CONNECTION_RULES_TEXT,
    resolve_scope,
    resolve_update_scope,
    validate_node_type,
    validate_edge_endpoints,
)

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


# 节点类型白名单，创建/更新时强制校验，禁止 agent 自创
VALID_NODE_TYPES = list(STANDARD_NODE_TYPES)


# 输入Schema
class CreateNodeInput(BaseModel):
    node_type: str = Field(description=f"节点类型。{NODE_TYPES_RULES_TEXT}")
    title: str = Field(description="节点标题")
    content: str = Field(default="", description="节点内容")
    chapter_elements: Optional[list[dict]] = Field(
        default=None,
        description=(
            "chapter 专用：本章情节元素列表，每项建议包含 title 和 content。"
            "元素不是节点类型，不要创建 element 节点；创建章节时把本章元素放在这里。"
        ),
    )
    layer: int = Field(
        default=0,
        description=f"垂直布局层级（整数，数字小的在上）。{NODE_LAYOUT_RULES_TEXT}",
    )
    scope: Optional[str] = Field(default=None, description="角色定位(character专用)：global=主角 / major=主要配角 / minor=次要配角(默认) / temp=临时角色。worldbuilding/style 固定 global，层级链(outline/volume/plot/chapter) 固定 local。**改角色定位必须用 scope 字段，不能只改 title 文字**")
    position_x: float = Field(description=f"X 坐标（画布水平位置）。{NODE_LAYOUT_RULES_TEXT}")
    position_y: float = Field(description=f"Y 坐标（画布垂直位置）。{NODE_LAYOUT_RULES_TEXT}")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class UpdateNodeInput(BaseModel):
    node_id: str = Field(description="节点ID")
    title: Optional[str] = Field(default=None, description="新标题")
    content: Optional[str] = Field(default=None, description="新内容")
    chapter_elements: Optional[list[dict]] = Field(
        default=None,
        description=(
            "chapter 专用：更新本章情节元素列表，每项建议包含 title 和 content。"
            "只更新 extra_data.chapter_elements，不覆盖 extra_data 中的其它字段。"
        ),
    )
    content_edit_instruction: Optional[str] = Field(
        default=None,
        description=(
            "局部编辑节点内容的用户原话。用于章节正文小改（改对话/措辞/删增少量段落）时，"
            "工具会读取现有 content，生成段落级 edits，校验后应用并返回 diff。"
            "不要和 content 同时传；content 表示整体覆盖。"
        ),
    )
    content_edit_context: Optional[str] = Field(
        default=None,
        description="局部编辑所需上下文（agent 已用查询工具备齐的大纲/角色/伏笔等原文）。仅配合 content_edit_instruction 使用。",
    )
    prev_chapter_node_id: Optional[str] = Field(
        default=None,
        description="局部编辑章节正文时可传上一章节点ID，工具会注入上一章正文作承接参考。",
    )
    node_type: Optional[str] = Field(default=None, description="新类型")
    layer: Optional[int] = Field(
        default=None,
        description=f"新的垂直层级。{NODE_LAYOUT_RULES_TEXT}",
    )
    scope: Optional[str] = Field(default=None, description="新的角色定位(character专用)：global=主角 / major=主要配角 / minor=次要配角 / temp=临时角色。**改角色定位必须改本字段，单独改 title 文字不会改变角色定位**")
    position_x: Optional[float] = Field(
        default=None,
        description=f"X 坐标。{NODE_LAYOUT_RULES_TEXT}",
    )
    position_y: Optional[float] = Field(
        default=None,
        description=f"Y 坐标。{NODE_LAYOUT_RULES_TEXT}",
    )
    locked: Optional[bool] = Field(
        default=None,
        description="是否固定节点（固定后坐标不可被移动）。仅由用户侧设置，agent 不应主动修改。",
    )
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class DeleteNodeInput(BaseModel):
    node_id: str = Field(description="节点ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class CreateEdgeInput(BaseModel):
    source_id: str = Field(
        description=f"源节点 ID。{EDGE_ENDPOINT_RULES_TEXT}",
    )
    target_id: str = Field(
        description=f"目标节点 ID。{EDGE_ENDPOINT_RULES_TEXT}",
    )
    edge_type: str = Field(default="uses", description="连线类型，用简短自然语言描述关系（如'包含'、'角色登场'、'伏笔埋设'、'场景关联'等，不超过100字符）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class DeleteEdgeInput(BaseModel):
    edge_id: str = Field(description="连线ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class UpdateEdgeInput(BaseModel):
    edge_id: str = Field(description="连线ID")
    edge_type: Optional[str] = Field(default=None, description="新的连线类型，短自然语言描述关系（不超过100字符）")
    label: Optional[str] = Field(
        default=None,
        description="深层关系说明（可选）。仅当 edge_type 与节点标题仍无法表达、必须在连线上补充的隐含语义时使用；常规包含/顺序关系留空。有内容时会显示在画布连线上。",
    )
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class BatchCreateNodesInput(BaseModel):
    nodes_data: list[dict] = Field(
        description=(
            "节点数据列表，每项含 node_type、title、position_x、position_y、layer 等。"
            "创建 chapter 时可带 chapter_elements；不要创建 element 节点。"
            f"{NODE_LAYOUT_RULES_TEXT}"
        ),
    )
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class BatchCreateEdgesInput(BaseModel):
    edges_data: list[dict] = Field(
        description=f"连线数据列表，每项含 source_id、target_id、edge_type。{EDGE_ENDPOINT_RULES_TEXT}",
    )
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


def _compact(node):
    """节点精简字段（不含正文），供邻居/索引返回。"""
    return {
        "id": node.id,
        "type": node.type,
        "title": node.title,
        "layer": node.layer,
        "scope": node.scope,
        "locked": bool(node.locked),
    }


def _resolve_update_scope(node, new_type, proposed_scope):
    """更新节点时解析最终作用域（委托 node_types 纯函数）。"""
    return resolve_update_scope(node.type, node.scope, new_type, proposed_scope)


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


def _detect_rect_issue(rect_a: dict, rect_b: dict) -> str:
    """包装 node_layout.detect_rect_issue，返回纯文本消息（无问题返回空串）。"""
    issue = detect_rect_issue(rect_a, rect_b)
    return issue["message"] if issue else ""


def _format_layout_warning(other_node, issue: dict) -> str:
    """把单条布局问题格式化为带对方节点标题的自然语言句子。"""
    title = other_node.title
    msg = issue["message"]
    if issue["type"] == "overlap":
        # 圆形重叠时 overlap_width/overlap_height 为 0，用 edge_distance(负值) 描述重叠深度
        if issue.get("overlap_width", 0) == 0 and issue.get("overlap_height", 0) == 0:
            depth = abs(issue.get("edge_distance", 0))
            return f"与节点「{title}」{msg}（重叠深度约 {depth:.0f}px）"
        return (f"与节点「{title}」{msg}"
                f"（水平重叠 {issue['overlap_width']}px，垂直重叠 {issue['overlap_height']}px）")
    if issue["type"] == "touching":
        return f"与节点「{title}」{msg}（当前边距 {issue['edge_distance']}px）"
    return f"与节点「{title}」{msg}"


def _collect_node_layout_warnings(db, work_id, target_node) -> list:
    """检测 target_node 与同 work 内其它节点的布局冲突，返回自然语言警告列表。"""
    others = db.query(Node).filter(
        Node.work_id == work_id, Node.id != target_node.id
    ).all()
    target_rect = node_rect(target_node)
    warnings = []
    for other in others:
        issue = detect_rect_issue(target_rect, node_rect(other))
        if issue:
            warnings.append(_format_layout_warning(other, issue))
    return warnings


def _collect_batch_layout_warnings(db, work_id, created_nodes) -> list:
    """批量创建后检测：每个新节点 vs 全量节点（含其它新节点），按节点对去重。"""
    all_nodes = db.query(Node).filter(Node.work_id == work_id).all()
    new_ids = {n.id for n in created_nodes}
    new_set = [n for n in all_nodes if n.id in new_ids]
    warnings = []
    seen_pairs = set()
    for node in new_set:
        node_r = node_rect(node)
        for other in all_nodes:
            if other.id == node.id:
                continue
            pair_key = tuple(sorted((node.id, other.id)))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            issue = detect_rect_issue(node_r, node_rect(other))
            if issue:
                warnings.append(_format_layout_warning(other, issue))
    return warnings


def _collect_edge_overlap_warnings(db, work_id) -> list:
    """检测作品内连线间的平行覆盖（同方向、区间重叠），返回自然语言警告列表。"""
    nodes = db.query(Node).filter(Node.work_id == work_id).all()
    edges = db.query(Edge).filter(Edge.work_id == work_id).all()
    return detect_edge_overlap(nodes, edges)


def _build_layout_hint(warnings: list) -> str:
    """根据警告数量生成给 agent 的处置提示。"""
    if not warnings:
        return ""
    return (
        f"检测到 {len(warnings)} 个布局问题。"
        "请直接调用 update_node 调整 position_x/position_y/layer 修复，不要询问用户是否修复。"
        "建议水平间距≥300px、垂直间距≥200px。"
        "每轮移动后调用 get_node_layout_issues 确认该节点 warnings 已清零；"
        "batch_create_nodes 多个警告时逐节点修复直至 layout_warnings 为空。"
        "若画布过于密集、确实无法完全消除冲突，须在最终回复中逐条列出未解决节点对及原因。"
    )


def _normalize_chapter_elements(chapter_elements) -> tuple[list[dict], str | None]:
    if chapter_elements is None:
        return [], None
    if not isinstance(chapter_elements, list):
        return [], "chapter_elements 必须是数组"
    normalized = []
    for idx, item in enumerate(chapter_elements):
        if not isinstance(item, dict):
            return [], f"chapter_elements[{idx}] 必须是对象"
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        if not title and not content:
            return [], f"chapter_elements[{idx}] 至少需要 title 或 content"
        normalized.append({
            "id": str(item.get("id") or f"chapter_element_{idx + 1}"),
            "title": title,
            "content": content,
            **{
                key: value
                for key, value in item.items()
                if key not in ("id", "title", "content")
            },
        })
    return normalized, None


def _extra_data_with_chapter_elements(extra_data, chapter_elements: list[dict] | None) -> dict:
    data = dict(extra_data or {})
    if chapter_elements is not None:
        data["chapter_elements"] = chapter_elements
    return data


# 同步实现
def _create_node_sync(node_type, title, content="", layer=0, position_x=None, position_y=None, scope=None, reason=None, chapter_elements=None):
    try:
        final_scope = resolve_scope(node_type, scope)
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    normalized_elements = None
    if chapter_elements is not None:
        if node_type != "chapter":
            return json.dumps({"error": "chapter_elements 只能用于 chapter 节点"}, ensure_ascii=False)
        normalized_elements, err = _normalize_chapter_elements(chapter_elements)
        if err:
            return json.dumps({"error": err}, ensure_ascii=False)

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
            scope=final_scope,
            extra_data=_extra_data_with_chapter_elements({}, normalized_elements),
            position_x=position_x,
            position_y=position_y,
        )
        db.add(node)
        db.commit()
        db.refresh(node)
        layout_warnings = _collect_node_layout_warnings(db, work_id, node) + _collect_edge_overlap_warnings(db, work_id)
        return json.dumps({
            "success": True,
            "node": _compact(node),
            "neighbors": [],
            "layout_warnings": layout_warnings,
            "layout_hint": _build_layout_hint(layout_warnings),
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _update_node_sync(
    node_id,
    title=None,
    content=None,
    node_type=None,
    layer=None,
    position_x=None,
    position_y=None,
    scope=None,
    locked=None,
    reason=None,
    content_edit_instruction=None,
    content_edit_context=None,
    prev_chapter_node_id=None,
    chapter_elements=None,
):
    if content_edit_instruction:
        return json.dumps({
            "success": False,
            "error": "content_edit_instruction 需要通过异步工具调用执行；普通同步更新请使用 content 整体覆盖。",
        }, ensure_ascii=False)
    if node_type is not None:
        try:
            validate_node_type(node_type)
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
    normalized_elements = None
    if chapter_elements is not None:
        normalized_elements, err = _normalize_chapter_elements(chapter_elements)
        if err:
            return json.dumps({"error": err}, ensure_ascii=False)
    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == node_id).first()
        if not node:
            return json.dumps({"error": "节点不存在"}, ensure_ascii=False)
        final_type_for_elements = node_type or node.type
        if chapter_elements is not None and final_type_for_elements != "chapter":
            return json.dumps({"error": "chapter_elements 只能用于 chapter 节点"}, ensure_ascii=False)
        # 锁定校验：被用户固定的节点，其坐标不可被移动
        is_locked = bool(node.locked)
        trying_move = (position_x is not None) or (position_y is not None)
        if is_locked and trying_move:
            return json.dumps({
                "success": False,
                "error": f"节点「{node.title}」已被用户锁定，坐标无法移动。请保留该节点当前位置，不要再次尝试调整其 position_x/position_y。",
            }, ensure_ascii=False)
        if title is not None:
            node.title = title
        if content is not None:
            node.content = content
            from app.services.chapter_history_service import clear_chapter_summary_on_content_change
            clear_chapter_summary_on_content_change(db, node)
        if node_type is not None:
            node.type = node_type
        if layer is not None:
            node.layer = layer
        if position_x is not None:
            node.position_x = position_x
        if position_y is not None:
            node.position_y = position_y
        if locked is not None:
            node.locked = locked
        if chapter_elements is not None:
            node.extra_data = _extra_data_with_chapter_elements(node.extra_data, normalized_elements)
        try:
            node.scope = _resolve_update_scope(node, node_type, scope)
        except ValueError as e:
            db.rollback()
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        db.commit()
        db.refresh(node)
        neighbors = _neighbor_items(db, node.id, node.work_id)
        layout_warnings = _collect_node_layout_warnings(db, node.work_id, node) + _collect_edge_overlap_warnings(db, node.work_id)
        return json.dumps({
            "success": True,
            "node": _compact(node),
            "neighbors": neighbors,
            "layout_warnings": layout_warnings,
            "layout_hint": _build_layout_hint(layout_warnings),
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


def _create_edge_sync(source_id, target_id, edge_type="uses", reason=None):
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
        endpoint_err = validate_edge_endpoints(source.type, target.type, source.scope, target.scope)
        if endpoint_err:
            return json.dumps({"error": endpoint_err}, ensure_ascii=False)
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
            label="",
            extra_data=build_edge_layout(source, target),
        )
        db.add(edge)
        db.commit()
        db.refresh(edge)
        neighbors = [
            {"node": _compact(target), "edge": {"edge_type": edge_type, "direction": "out"}},
            {"node": _compact(source), "edge": {"edge_type": edge_type, "direction": "in"}},
        ]
        layout_warnings = _collect_edge_overlap_warnings(db, work_id)
        return json.dumps({
            "success": True,
            "edge": {"id": edge.id, "source_id": source_id, "source_title": source.title, "target_id": target_id, "target_title": target.title, "edge_type": edge_type, "label": ""},
            "neighbors": neighbors,
            "layout_warnings": layout_warnings,
            "layout_hint": _build_layout_hint(layout_warnings),
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
        layout_warnings = _collect_edge_overlap_warnings(db, edge.work_id)
        return json.dumps({
            "success": True,
            "edge": {"id": edge.id, "source_id": edge.source_id, "target_id": edge.target_id, "edge_type": edge.edge_type, "label": edge.label},
            "neighbors": endpoints,
            "layout_warnings": layout_warnings,
            "layout_hint": _build_layout_hint(layout_warnings),
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

    for data in nodes_data:
        node_type = data.get("node_type") or data.get("type")
        if not node_type:
            return json.dumps({"error": "节点类型不能为空"}, ensure_ascii=False)
        try:
            resolve_scope(node_type, data.get("scope"))
        except ValueError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        if data.get("chapter_elements") is not None:
            if node_type != "chapter":
                return json.dumps({"error": "chapter_elements 只能用于 chapter 节点"}, ensure_ascii=False)
            _, err = _normalize_chapter_elements(data.get("chapter_elements"))
            if err:
                return json.dumps({"error": err}, ensure_ascii=False)

    db = _get_db()
    try:
        created_nodes = []
        for data in nodes_data:
            node_type = data.get("node_type") or data.get("type")
            if not node_type or not node_type.strip():
                continue
            layer = data.get("layer", 0)
            position_x = data.get("position_x")
            position_y = data.get("position_y")
            scope = resolve_scope(node_type, data.get("scope"))
            normalized_elements = None
            if data.get("chapter_elements") is not None:
                normalized_elements, _ = _normalize_chapter_elements(data.get("chapter_elements"))
            node = Node(
                id=str(uuid.uuid4()),
                work_id=work_id,
                type=node_type,
                title=data.get("title", "未命名"),
                content=data.get("content", ""),
                extra_data=_extra_data_with_chapter_elements({}, normalized_elements),
                layer=layer,
                scope=scope,
                position_x=position_x if position_x is not None else 0.0,
                position_y=position_y if position_y is not None else 0.0,
            )
            db.add(node)
            created_nodes.append(node)
        
        db.commit()
        for node in created_nodes:
            db.refresh(node)
        layout_warnings = _collect_batch_layout_warnings(db, work_id, created_nodes) + _collect_edge_overlap_warnings(db, work_id)
        return json.dumps({
            "success": True,
            "nodes": [_compact(n) for n in created_nodes],
            "neighbors": [],
            "count": len(created_nodes),
            "layout_warnings": layout_warnings,
            "layout_hint": _build_layout_hint(layout_warnings),
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
            if validate_edge_endpoints(source.type, target.type, source.scope, target.scope):
                continue
            edge = Edge(
                id=str(uuid.uuid4()),
                work_id=work_id,
                source_id=source_id,
                target_id=target_id,
                edge_type=edge_type,
                label="",
                extra_data=build_edge_layout(source, target),
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
        layout_warnings = _collect_edge_overlap_warnings(db, work_id)
        return json.dumps({
            "success": True,
            "edges": [{"id": e.id, "source_id": e.source_id, "target_id": e.target_id, "edge_type": e.edge_type} for e in created_edges],
            "neighbors": endpoint_ids,
            "count": len(created_edges),
            "layout_warnings": layout_warnings,
            "layout_hint": _build_layout_hint(layout_warnings),
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


# 异步包装
async def _create_node_async(node_type, title, content="", layer=0, position_x=None, position_y=None, scope=None, reason=None, chapter_elements=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_create_node_sync, node_type, title, content, layer, position_x, position_y, scope, reason, chapter_elements))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "create", "node_type": node_type})
    except Exception:
        logger.warning("_create_node_async 触发 nodes_updated 失败", exc_info=True)
    return result


async def _update_node_content_edit_async(
    node_id,
    edit_instruction,
    context="",
    title=None,
    node_type=None,
    layer=None,
    position_x=None,
    position_y=None,
    scope=None,
    locked=None,
    reason=None,
    prev_chapter_node_id=None,
    chapter_elements=None,
):
    from app.services.agents.llm import get_llm, context_model_pref_kwargs
    from app.services.agents.tools.chapter_tools import (
        _build_edit_chapter_messages,
        _collect_chapter_elements,
        _parse_edits_json,
        _read_prev_chapter_content,
    )
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

    if node_type is not None:
        try:
            validate_node_type(node_type)
        except ValueError as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    db = _get_db()
    try:
        node = db.query(Node).filter(Node.id == node_id).first()
        if not node:
            return json.dumps({"success": False, "error": "节点不存在"}, ensure_ascii=False)
        if node.type != "chapter":
            return json.dumps({"success": False, "error": "局部正文编辑目前仅支持 chapter 节点"}, ensure_ascii=False)
        if not (node.content or "").strip():
            return json.dumps({
                "success": False,
                "error": "节点内容为空，无法局部编辑；请使用 content 整体写入。",
            }, ensure_ascii=False)

        is_locked = bool(node.locked)
        trying_move = (position_x is not None) or (position_y is not None)
        if is_locked and trying_move:
            return json.dumps({
                "success": False,
                "error": f"节点「{node.title}」已被用户锁定，坐标无法移动。请保留该节点当前位置，不要再次尝试调整其 position_x/position_y。",
            }, ensure_ascii=False)

        old_content = node.content or ""
        effective_work_id = node.work_id
        global_nodes = get_global_nodes(db, effective_work_id)
        global_context = format_global_context(global_nodes)
        prev_chapter = _read_prev_chapter_content(db, prev_chapter_node_id)
        elements = _collect_chapter_elements(db, node_id, effective_work_id)

        llm = get_llm(temperature=0.3, streaming=True, **context_model_pref_kwargs())
        messages = _build_edit_chapter_messages(
            edit_instruction,
            old_content,
            context or "",
            global_context,
            prev_chapter,
            elements,
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
            }, ensure_ascii=False)

        edits = parsed["edits"]
        paragraphs = split_paragraphs(old_content)
        validation_errors = validate_edits(edits, paragraphs)
        if validation_errors:
            return json.dumps({
                "success": False,
                "error": validation_errors[0],
                "validation_errors": validation_errors,
            }, ensure_ascii=False)

        try:
            new_content = apply_edits(old_content, edits)
        except ValueError as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

        diff = build_chapter_edit_diff(old_content, new_content, edits)

        if title is not None:
            node.title = title
        node.content = new_content
        if node_type is not None:
            node.type = node_type
        if layer is not None:
            node.layer = layer
        if position_x is not None:
            node.position_x = position_x
        if position_y is not None:
            node.position_y = position_y
        if locked is not None:
            node.locked = locked
        if chapter_elements is not None:
            if node.type != "chapter" and node_type != "chapter":
                return json.dumps({"success": False, "error": "chapter_elements 只能用于 chapter 节点"}, ensure_ascii=False)
            normalized_elements, err = _normalize_chapter_elements(chapter_elements)
            if err:
                return json.dumps({"success": False, "error": err}, ensure_ascii=False)
            node.extra_data = _extra_data_with_chapter_elements(node.extra_data, normalized_elements)
        try:
            node.scope = _resolve_update_scope(node, node_type, scope)
        except ValueError as e:
            db.rollback()
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

        clear_chapter_summary_on_content_change(db, node)
        db.commit()
        db.refresh(node)

        neighbors = _neighbor_items(db, node.id, node.work_id)
        layout_warnings = _collect_node_layout_warnings(db, node.work_id, node) + _collect_edge_overlap_warnings(db, node.work_id)
        word_count = chapter_body_word_count(new_content)
        old_word_count = chapter_body_word_count(old_content)
        result = {
            "success": True,
            "node": _compact(node),
            "neighbors": neighbors,
            "layout_warnings": layout_warnings,
            "layout_hint": _build_layout_hint(layout_warnings),
            "word_count": word_count,
            "word_count_delta": word_count - old_word_count,
            "diff": diff,
            "content_edit": {
                "word_count": word_count,
                "word_count_delta": word_count - old_word_count,
                "diff": diff,
            },
        }

        if emit:
            await emit("chapter_edit_diff", {
                "chapter_node_id": node_id,
                "title": node.title,
                "word_count": word_count,
                "word_count_delta": word_count - old_word_count,
                "diff": diff,
            })
            await emit("nodes_updated", {"action": "update", "node_id": node_id})

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


async def _update_node_async(
    node_id,
    title=None,
    content=None,
    node_type=None,
    layer=None,
    position_x=None,
    position_y=None,
    scope=None,
    locked=None,
    reason=None,
    content_edit_instruction=None,
    content_edit_context=None,
    prev_chapter_node_id=None,
    chapter_elements=None,
):
    if content is not None and content_edit_instruction:
        return json.dumps({
            "success": False,
            "error": "content 和 content_edit_instruction 不能同时传；content 是整体覆盖，content_edit_instruction 是局部编辑。",
        }, ensure_ascii=False)
    if content_edit_instruction:
        return await _update_node_content_edit_async(
            node_id,
            content_edit_instruction,
            content_edit_context or "",
            title=title,
            node_type=node_type,
            layer=layer,
            position_x=position_x,
            position_y=position_y,
            scope=scope,
            locked=locked,
            reason=reason,
            prev_chapter_node_id=prev_chapter_node_id,
            chapter_elements=chapter_elements,
        )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_update_node_sync, node_id, title, content, node_type, layer, position_x, position_y, scope, locked, reason, None, None, None, chapter_elements))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "update", "node_id": node_id})
    except Exception:
        logger.warning("_update_node_async 触发 nodes_updated 失败", exc_info=True)
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
    except Exception:
        logger.warning("_delete_node_async 触发 nodes_updated 失败", exc_info=True)
    return result


async def _create_edge_async(source_id, target_id, edge_type="uses", reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_create_edge_sync, source_id, target_id, edge_type, reason))
    # 触发画布更新事件
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "edge_create", "edge_type": edge_type})
    except Exception:
        logger.warning("_create_edge_async 触发 nodes_updated 失败", exc_info=True)
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
    except Exception:
        logger.warning("_delete_edge_async 触发 nodes_updated 失败", exc_info=True)
    return result


async def _update_edge_async(edge_id, edge_type=None, label=None, reason=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, partial(_update_edge_sync, edge_id, edge_type, label, reason)
    )
    try:
        data = json.loads(result)
        if data.get("success"):
            emit = _get_emit()
            if emit:
                await emit("nodes_updated", {"action": "edge_update", "edge_id": edge_id})
    except Exception:
        logger.warning("_update_edge_async 触发 nodes_updated 失败", exc_info=True)
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
    except Exception:
        logger.warning("_batch_create_nodes_async 触发 nodes_updated 失败", exc_info=True)
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
    except Exception:
        logger.warning("_batch_create_edges_async 触发 nodes_updated 失败", exc_info=True)
    return result


# 创建工具
create_node = StructuredTool.from_function(
    coroutine=_create_node_async,
    func=_create_node_sync,
    name="create_node",
    description=(
        "创建新节点。返回 layout_warnings 与 layout_hint（有重叠/间距问题时须按 hint 修复）。"
        f"{NODE_TYPES_RULES_TEXT} {NODE_LAYOUT_RULES_TEXT}"
    ),
    args_schema=CreateNodeInput,
)

update_node = StructuredTool.from_function(
    coroutine=_update_node_async,
    func=_update_node_sync,
    name="update_node",
    description=(
        "更新节点属性或调整布局（position_x/y、layer）。"
        "章节正文小改时不要整体重写 content，改传 content_edit_instruction 做段落级局部编辑并返回 diff。"
        f"{NODE_LAYOUT_RULES_TEXT} "
        "返回 layout_warnings 与 layout_hint；有警告时须修复直至 warnings 为空。"
    ),
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
    description=(
        "在两个节点之间创建连线。创建时不写连线 label，仅用 edge_type 表达关系。"
        f"{EDGE_ENDPOINT_RULES_TEXT} {EDGE_CONNECTION_RULES_TEXT}"
    ),
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
    description="更新连线的 edge_type；必要时用 label 补充深层关系说明（有内容时显示在画布连线上）。",
    args_schema=UpdateEdgeInput,
)

batch_create_nodes = StructuredTool.from_function(
    coroutine=_batch_create_nodes_async,
    func=_batch_create_nodes_sync,
    name="batch_create_nodes",
    description=(
        "批量创建多个节点。返回 layout_warnings 与 layout_hint；"
        f"{NODE_LAYOUT_RULES_TEXT} "
        "多个警告时逐节点修复直至 layout_warnings 为空。"
    ),
    args_schema=BatchCreateNodesInput,
)

batch_create_edges = StructuredTool.from_function(
    coroutine=_batch_create_edges_async,
    func=_batch_create_edges_sync,
    name="batch_create_edges",
    description=(
        "批量创建多个连线。每条仅需 source_id、target_id、edge_type；不写 label。"
        f"{EDGE_ENDPOINT_RULES_TEXT}"
    ),
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
