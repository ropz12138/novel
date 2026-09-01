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

from models.node import Node
from models.edge import Edge
from services.edge_layout_service import build_edge_layout
from services.edge_relation import validate_hierarchy_structure
from node_types import (
    STANDARD_NODE_TYPES,
    NODE_TYPES_RULES_TEXT,
    NODE_LAYOUT_RULES_TEXT,
    NODE_SORT_ORDER_RULES_TEXT,
    MISSING_SORT_ORDER_ERROR,
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
    from database import SessionLocal
    return SessionLocal()


def _get_current_work_id():
    """获取当前work_id"""
    try:
        from services.agents.supervisor import get_context
        return get_context().get("work_id")
    except:
        return None


def _get_emit():
    """获取事件发射函数"""
    try:
        from services.agents.supervisor import get_context
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
    storylines: Optional[list[dict]] = Field(
        default=None,
        description=(
            "character 专用：角色发展线列表，写入 extra_data.storylines，不覆盖 extra_data 中的其它字段。"
            "每项必须含 name（线名）和 body（轨迹节点的字符串列表，按时间顺序）；"
            "description 为该线的说明文字。"
        ),
    )
    sort_order: int = Field(description=NODE_SORT_ORDER_RULES_TEXT)
    layer: int = Field(
        default=0,
        description=f"垂直布局层级（整数，数字小的在上）。{NODE_LAYOUT_RULES_TEXT}",
    )
    scope: Optional[str] = Field(default=None, description="角色定位(character专用)：global=主角 / major=主要配角 / minor=次要配角(默认) / temp=临时角色。worldbuilding/note 固定 global，层级链(outline/volume/plot/chapter) 固定 local。**改角色定位必须用 scope 字段，不能只改 title 文字**")
    position_x: Optional[float] = Field(default=None, description=NODE_LAYOUT_RULES_TEXT)
    position_y: Optional[float] = Field(default=None, description=NODE_LAYOUT_RULES_TEXT)
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class UpdateNodeInput(BaseModel):
    node_id: str = Field(description="节点ID")
    title: Optional[str] = Field(default=None, description="新标题")
    content: Optional[str] = Field(default=None, description="新内容")
    sort_order: Optional[int] = Field(
        default=None,
        description=f"调整同级显示顺序。{NODE_SORT_ORDER_RULES_TEXT}",
    )
    chapter_elements: Optional[list[dict]] = Field(
        default=None,
        description=(
            "chapter 专用：更新本章情节元素列表，每项建议包含 title 和 content。"
            "只更新 extra_data.chapter_elements，不覆盖 extra_data 中的其它字段。"
        ),
    )
    storylines: Optional[list[dict]] = Field(
        default=None,
        description=(
            "character 专用：更新角色发展线列表，每项必须含 name 和 body（字符串列表）；"
            "description 为该线的说明。只更新 extra_data.storylines，不覆盖 extra_data 中的其它字段。"
        ),
    )
    content_edit_instruction: Optional[str] = Field(
        default=None,
        description=(
            "局部编辑节点 content 的用户原话。用于任何节点文本小改（改对话/措辞/删增少量段落/标记高亮）时，"
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
        description="局部编辑章节正文时可传上一章节点ID，工具会注入上一章正文作承接参考；非章节节点会忽略。",
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
            "节点数据列表，每项必须含 node_type、title、sort_order。"
            "创建 chapter 时可带 chapter_elements；创建 character 时可带 storylines；不要创建 element 节点。"
            f"{NODE_SORT_ORDER_RULES_TEXT}{NODE_LAYOUT_RULES_TEXT}"
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
        "sort_order": node.sort_order,
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


def _chapter_has_character_edge(db, work_id, chapter_node_id: str) -> bool:
    """章节是否已与任意 character 节点相连（方向不限）。"""
    character_ids = [
        row[0]
        for row in db.query(Node.id).filter(
            Node.work_id == work_id,
            Node.type == "character",
        ).all()
    ]
    if not character_ids:
        return False
    linked = db.query(Edge.id).filter(
        Edge.work_id == work_id,
        (
            ((Edge.source_id == chapter_node_id) & (Edge.target_id.in_(character_ids)))
            | ((Edge.target_id == chapter_node_id) & (Edge.source_id.in_(character_ids)))
        ),
    ).first()
    return linked is not None


def _collect_chapter_character_relation_warnings(db, work_id, chapter_node) -> list:
    """章节创建后校验：未连接任何角色节点时返回自然语言警告。"""
    if chapter_node is None or chapter_node.type != "chapter":
        return []
    character_count = db.query(Node.id).filter(
        Node.work_id == work_id,
        Node.type == "character",
    ).count()
    title = chapter_node.title or "未命名章节"
    if character_count == 0:
        return [
            f"章节「{title}」创建后画布上尚无角色节点，且未建立章节-角色连线。"
            "请先创建本章出场角色节点，再为章节与角色建立连线（如「登场」「影响」）。"
        ]
    if _chapter_has_character_edge(db, work_id, chapter_node.id):
        return []
    return [
        f"章节「{title}」尚未连接任何角色节点。"
        "请为本章出场角色建立章节-角色连线（如「登场」「影响」）。"
    ]


def _collect_batch_chapter_character_relation_warnings(db, work_id, created_nodes) -> list:
    """批量创建后，对每个新建 chapter 做角色连线校验。"""
    warnings = []
    for node in created_nodes:
        warnings.extend(_collect_chapter_character_relation_warnings(db, work_id, node))
    return warnings


def _build_relation_hint(warnings: list) -> str:
    """根据章节-角色关系警告生成给 agent 的处置提示。"""
    if not warnings:
        return ""
    return (
        f"检测到 {len(warnings)} 个章节-角色关系问题。"
        "请直接补全：必要时用 create_node(type=character) 创建角色，"
        "再用 create_edge / batch_create_edges 连接章节与角色；不要询问用户是否修复。"
        "连线 edge_type 用简短自然语言（如「登场」「影响」「同行」）。"
    )


def _relation_feedback_fields(db, work_id, nodes) -> dict:
    """构造 create 返回中的 relation_warnings / relation_hint。"""
    if isinstance(nodes, list):
        warnings = _collect_batch_chapter_character_relation_warnings(db, work_id, nodes)
    else:
        warnings = _collect_chapter_character_relation_warnings(db, work_id, nodes)
    return {
        "relation_warnings": warnings,
        "relation_hint": _build_relation_hint(warnings),
    }


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


def _normalize_storylines(storylines) -> tuple[list[dict], str | None]:
    if storylines is None:
        return [], None
    if not isinstance(storylines, list):
        return [], "storylines 必须是数组"
    normalized = []
    for idx, item in enumerate(storylines):
        if not isinstance(item, dict):
            return [], f"storylines[{idx}] 必须是对象"
        name = str(item.get("name") or "").strip()
        if not name:
            return [], f"storylines[{idx}] 需要 name"
        description = str(item.get("description") or "").strip()
        body = item.get("body")
        if not isinstance(body, list):
            return [], f"storylines[{idx}].body 必须是字符串列表"
        steps = []
        for bidx, step in enumerate(body):
            if not isinstance(step, str):
                return [], f"storylines[{idx}].body[{bidx}] 必须是字符串"
            text = step.strip()
            if not text:
                return [], f"storylines[{idx}].body[{bidx}] 不能为空"
            steps.append(text)
        if not steps:
            return [], f"storylines[{idx}].body 不能为空"
        normalized.append({
            "name": name,
            "description": description,
            "body": steps,
        })
    return normalized, None


def _merge_extra_data_fields(extra_data, *, chapter_elements=None, storylines=None) -> dict:
    data = dict(extra_data or {})
    if chapter_elements is not None:
        data["chapter_elements"] = chapter_elements
    if storylines is not None:
        data["storylines"] = storylines
    return data


def _extra_data_with_chapter_elements(extra_data, chapter_elements: list[dict] | None) -> dict:
    return _merge_extra_data_fields(extra_data, chapter_elements=chapter_elements)


# 同步实现
def _create_node_sync(node_type, title, content="", layer=0, position_x=None, position_y=None, scope=None, reason=None, chapter_elements=None, storylines=None, sort_order=None):
    if sort_order is None:
        return json.dumps({"error": MISSING_SORT_ORDER_ERROR}, ensure_ascii=False)
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
    normalized_storylines = None
    if storylines is not None:
        if node_type != "character":
            return json.dumps({"error": "storylines 只能用于 character 节点"}, ensure_ascii=False)
        normalized_storylines, err = _normalize_storylines(storylines)
        if err:
            return json.dumps({"error": err}, ensure_ascii=False)

    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    if node_type == "chapter" and content:
        from services.plot_highlight_service import validate_plot_highlights
        highlight_validation = validate_plot_highlights(content)
        if not highlight_validation.valid:
            return json.dumps({
                "success": False,
                "error": "章节剧情高亮未通过质量校验，请修正后重新创建",
                "plot_highlight_validation": highlight_validation.as_dict(),
            }, ensure_ascii=False)
    
    db = _get_db()
    try:
        node = Node(
            id=str(uuid.uuid4()),
            work_id=work_id,
            type=node_type,
            title=title,
            content=content,
            layer=layer,
            sort_order=sort_order,
            scope=final_scope,
            extra_data=_merge_extra_data_fields(
                {},
                chapter_elements=normalized_elements,
                storylines=normalized_storylines,
            ),
            position_x=position_x,
            position_y=position_y,
        )
        db.add(node)
        db.commit()
        db.refresh(node)
        return json.dumps({
            "success": True,
            "node": _compact(node),
            "neighbors": [],
            **_relation_feedback_fields(db, work_id, node),
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
    storylines=None,
    sort_order=None,
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
    normalized_storylines = None
    if storylines is not None:
        normalized_storylines, err = _normalize_storylines(storylines)
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
        if storylines is not None and final_type_for_elements != "character":
            return json.dumps({"error": "storylines 只能用于 character 节点"}, ensure_ascii=False)
        if content is not None and final_type_for_elements == "chapter":
            from services.plot_highlight_service import validate_plot_highlights
            highlight_validation = validate_plot_highlights(content)
            if not highlight_validation.valid:
                return json.dumps({
                    "success": False,
                    "error": "章节剧情高亮未通过质量校验，请修正后重新写入",
                    "plot_highlight_validation": highlight_validation.as_dict(),
                }, ensure_ascii=False)
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
            from services.chapter_history_service import clear_chapter_summary_on_content_change
            clear_chapter_summary_on_content_change(db, node)
        if node_type is not None:
            node.type = node_type
        if layer is not None:
            node.layer = layer
        if sort_order is not None:
            node.sort_order = sort_order
        if position_x is not None:
            node.position_x = position_x
        if position_y is not None:
            node.position_y = position_y
        if locked is not None:
            node.locked = locked
        if chapter_elements is not None or storylines is not None:
            node.extra_data = _merge_extra_data_fields(
                node.extra_data,
                chapter_elements=normalized_elements if chapter_elements is not None else None,
                storylines=normalized_storylines if storylines is not None else None,
            )
        try:
            node.scope = _resolve_update_scope(node, node_type, scope)
        except ValueError as e:
            db.rollback()
            return json.dumps({"error": str(e)}, ensure_ascii=False)
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
        structure_err = validate_hierarchy_structure(db, work_id, source, target)
        if structure_err:
            return json.dumps({"error": structure_err}, ensure_ascii=False)
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
        return json.dumps({
            "success": True,
            "edge": {"id": edge.id, "source_id": source_id, "source_title": source.title, "target_id": target_id, "target_title": target.title, "edge_type": edge_type, "label": ""},
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

    for data in nodes_data:
        node_type = data.get("node_type") or data.get("type")
        if not node_type:
            return json.dumps({"error": "节点类型不能为空"}, ensure_ascii=False)
        if data.get("sort_order") is None:
            return json.dumps(
                {"error": f"{data.get('title', '未命名')}：{MISSING_SORT_ORDER_ERROR}"},
                ensure_ascii=False,
            )
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
        if data.get("storylines") is not None:
            if node_type != "character":
                return json.dumps({"error": "storylines 只能用于 character 节点"}, ensure_ascii=False)
            _, err = _normalize_storylines(data.get("storylines"))
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
            normalized_storylines = None
            if data.get("storylines") is not None:
                normalized_storylines, _ = _normalize_storylines(data.get("storylines"))
            node = Node(
                id=str(uuid.uuid4()),
                work_id=work_id,
                type=node_type,
                title=data.get("title", "未命名"),
                content=data.get("content", ""),
                extra_data=_merge_extra_data_fields(
                    {},
                    chapter_elements=normalized_elements,
                    storylines=normalized_storylines,
                ),
                layer=layer,
                sort_order=data["sort_order"],
                scope=scope,
                position_x=position_x if position_x is not None else 0.0,
                position_y=position_y if position_y is not None else 0.0,
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
            **_relation_feedback_fields(db, work_id, created_nodes),
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
            structure_err = validate_hierarchy_structure(db, work_id, source, target)
            if structure_err:
                db.rollback()
                return json.dumps({"error": structure_err}, ensure_ascii=False)
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
            # 让同一批次内后续的单父校验能看到刚加入的边
            db.flush()
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
async def _create_node_async(node_type, title, content="", layer=0, position_x=None, position_y=None, scope=None, reason=None, chapter_elements=None, storylines=None, sort_order=None):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_create_node_sync, node_type, title, content, layer, position_x, position_y, scope, reason, chapter_elements, storylines, sort_order))
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
    storylines=None,
    sort_order=None,
):
    from services.agents.llm import get_llm, context_model_pref_kwargs
    from services.chapter_edit_agent import (
        build_edit_chapter_messages,
        collect_chapter_elements,
        parse_edits_json,
        read_previous_chapter_content,
    )
    from services.chapter_edit_service import (
        apply_edits,
        build_chapter_edit_diff,
        split_paragraphs,
        validate_edits,
    )
    from services.chapter_history_service import clear_chapter_summary_on_content_change
    from services.chapter_word_count import chapter_body_word_count
    from services.global_context import get_global_nodes, format_global_context
    from services.llm_stream import chunk_to_ai_message, emit_llm_stream_deltas

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
        is_chapter_edit = node.type == "chapter"
        prev_chapter = read_previous_chapter_content(db, prev_chapter_node_id) if is_chapter_edit else ""
        elements = collect_chapter_elements(db, node_id, effective_work_id) if is_chapter_edit else []

        llm = get_llm(temperature=0.3, streaming=True, **context_model_pref_kwargs())
        messages = build_edit_chapter_messages(
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
            parsed = parse_edits_json(raw)
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
        if sort_order is not None:
            node.sort_order = sort_order
        if position_x is not None:
            node.position_x = position_x
        if position_y is not None:
            node.position_y = position_y
        if locked is not None:
            node.locked = locked
        if chapter_elements is not None or storylines is not None:
            if chapter_elements is not None and node.type != "chapter" and node_type != "chapter":
                return json.dumps({"success": False, "error": "chapter_elements 只能用于 chapter 节点"}, ensure_ascii=False)
            if storylines is not None and node.type != "character" and node_type != "character":
                return json.dumps({"success": False, "error": "storylines 只能用于 character 节点"}, ensure_ascii=False)
            normalized_elements = None
            if chapter_elements is not None:
                normalized_elements, err = _normalize_chapter_elements(chapter_elements)
                if err:
                    return json.dumps({"success": False, "error": err}, ensure_ascii=False)
            normalized_storylines = None
            if storylines is not None:
                normalized_storylines, err = _normalize_storylines(storylines)
                if err:
                    return json.dumps({"success": False, "error": err}, ensure_ascii=False)
            node.extra_data = _merge_extra_data_fields(
                node.extra_data,
                chapter_elements=normalized_elements if chapter_elements is not None else None,
                storylines=normalized_storylines if storylines is not None else None,
            )
        try:
            node.scope = _resolve_update_scope(node, node_type, scope)
        except ValueError as e:
            db.rollback()
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

        clear_chapter_summary_on_content_change(db, node)
        db.commit()
        db.refresh(node)

        neighbors = _neighbor_items(db, node.id, node.work_id)
        word_count = chapter_body_word_count(new_content)
        old_word_count = chapter_body_word_count(old_content)
        result = {
            "success": True,
            "node": _compact(node),
            "neighbors": neighbors,
            "text_count": len(new_content),
            "text_count_delta": len(new_content) - len(old_content),
            "word_count": word_count,
            "word_count_delta": word_count - old_word_count,
            "diff": diff,
            "content_edit": {
                "text_count": len(new_content),
                "text_count_delta": len(new_content) - len(old_content),
                "word_count": word_count,
                "word_count_delta": word_count - old_word_count,
                "diff": diff,
            },
        }
        if node.type == "chapter":
            from services.plot_highlight_service import validate_plot_highlights
            result["plot_highlight_validation"] = validate_plot_highlights(new_content).as_dict()

        if emit:
            diff_event_data = {
                "node_id": node_id,
                "chapter_node_id": node_id,
                "node_type": node.type,
                "title": node.title,
                "text_count": len(new_content),
                "text_count_delta": len(new_content) - len(old_content),
                "word_count": word_count,
                "word_count_delta": word_count - old_word_count,
                "diff": diff,
            }
            if node.type == "chapter":
                await emit("chapter_edit_diff", diff_event_data)
            else:
                await emit("node_content_diff", diff_event_data)
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
    storylines=None,
    sort_order=None,
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
            storylines=storylines,
            sort_order=sort_order,
        )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_update_node_sync, node_id, title, content, node_type, layer, position_x, position_y, scope, locked, reason, None, None, None, chapter_elements, storylines, sort_order))
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
        "创建新节点。"
        "创建 chapter 时返回 relation_warnings 与 relation_hint："
        "若章节未连接任何角色节点，须按 hint 补建角色并 create_edge 连接。"
        f"{NODE_TYPES_RULES_TEXT} {NODE_LAYOUT_RULES_TEXT}"
    ),
    args_schema=CreateNodeInput,
)

update_node = StructuredTool.from_function(
    coroutine=_update_node_async,
    func=_update_node_sync,
    name="update_node",
    description=(
        "更新节点属性。"
        "任何节点文本小改时不要整体重写 content，改传 content_edit_instruction 做段落级局部编辑并返回 diff；"
        "整篇重写或空节点首次写入才使用 content 全量覆盖。"
        f"{NODE_LAYOUT_RULES_TEXT}"
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
        "批量创建多个节点。"
        f"{NODE_LAYOUT_RULES_TEXT} "
        "若创建了 chapter，返回 relation_warnings 与 relation_hint："
        "章节未连角色时须补建角色并 create_edge / batch_create_edges 连接。"
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
