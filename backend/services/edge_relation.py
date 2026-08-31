"""关系类别派生与层级结构校验。

关系类别不作为字段存储，而是从节点类型派生。节点类型经 `validate_node_type`
强校验为固定枚举，层级链顺序固定为 outline → volume → plot → chapter，
因此类型本身已经承载了结构信息，无需在边上再存一份。

判定必须使用"严格降一级"，不能只判断两端是否都属于层级链类型：
chapter → chapter 的边两端都是层级链类型，若按后者判定会把前一章当成
后一章的父节点，导致树深度错乱。
"""
from models.edge import Edge
from models.node import Node

RELATION_HIERARCHY = "hierarchy"
RELATION_SEQUENCE = "sequence"
RELATION_REFERENCE = "reference"

# 层级链顺序，索引即层级序号
HIERARCHY_CHAIN = ("outline", "volume", "plot", "chapter")
_LEVELS = {node_type: level for level, node_type in enumerate(HIERARCHY_CHAIN)}


def hierarchy_level(node_type: str) -> int | None:
    """返回层级链序号；非层级链类型返回 None。"""
    return _LEVELS.get((node_type or "").strip())


def derive_relation_kind(source_type: str, target_type: str) -> str | None:
    """派生关系类别。返回 None 表示该组合非法，调用方必须拒绝。"""
    source_level = hierarchy_level(source_type)
    target_level = hierarchy_level(target_type)

    if source_level is None or target_level is None:
        return RELATION_REFERENCE

    if target_level == source_level:
        return RELATION_SEQUENCE
    if target_level == source_level + 1:
        return RELATION_HIERARCHY
    return None


def validate_relation_types(source_type: str, target_type: str) -> str | None:
    """校验类型组合，返回错误消息或 None。"""
    if derive_relation_kind(source_type, target_type) is not None:
        return None

    source_level = hierarchy_level(source_type)
    target_level = hierarchy_level(target_type)
    if target_level < source_level:
        return (
            f"层级链连线方向错误：{source_type} → {target_type}。"
            f"父子连线必须自上而下（{' → '.join(HIERARCHY_CHAIN)}），"
            f"同级顺序关系请让两端为同一类型。"
        )
    return (
        f"层级链不允许跨级连接：{source_type} → {target_type}。"
        f"父子连线只能降一级（{' → '.join(HIERARCHY_CHAIN)}），"
        f"请补齐中间层级节点。"
    )


def find_hierarchy_parent_id(db, work_id: str, target: Node) -> str | None:
    """返回 target 已有的 hierarchy 父节点 id，没有则返回 None。"""
    rows = (
        db.query(Edge.source_id, Node.type)
        .join(Node, Node.id == Edge.source_id)
        .filter(Edge.work_id == work_id, Edge.target_id == target.id)
        .all()
    )
    for source_id, source_type in rows:
        if derive_relation_kind(source_type, target.type) == RELATION_HIERARCHY:
            return source_id
    return None


def validate_hierarchy_structure(db, work_id: str, source: Node, target: Node) -> str | None:
    """校验一条待创建连线的结构合法性，返回错误消息或 None。

    环检测无需实现：hierarchy 边要求层级序号严格递增，而环必须回到起点层级，
    跨级与反向连接又已在类型判定阶段被拒绝，因此环在构造上不可能出现。
    """
    if source.id == target.id:
        return "连线的两端不能是同一个节点"

    type_err = validate_relation_types(source.type, target.type)
    if type_err:
        return type_err

    if derive_relation_kind(source.type, target.type) != RELATION_HIERARCHY:
        return None

    existing_parent_id = find_hierarchy_parent_id(db, work_id, target)
    if existing_parent_id is None:
        return None

    if existing_parent_id == source.id:
        return f"{source.title} → {target.title} 的父子连线已存在"

    parent_title = db.query(Node.title).filter(Node.id == existing_parent_id).scalar() or existing_parent_id
    return (
        f"{target.title} 已经挂在「{parent_title}」下，一个节点只能有一个父节点。"
        f"若要改挂到「{source.title}」，请先删除原有的父子连线。"
    )
