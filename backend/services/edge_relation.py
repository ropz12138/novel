"""章节独立排序；资料关联由章节字段表达。"""
RELATION_REFERENCE = "reference"


def derive_relation_kind(source_type: str, target_type: str) -> str | None:
    from node_types import STANDARD_NODE_TYPES
    if source_type not in STANDARD_NODE_TYPES or target_type not in STANDARD_NODE_TYPES:
        return None
    if source_type == target_type == "chapter":
        return None
    return RELATION_REFERENCE


def validate_relation_types(source_type: str, target_type: str) -> str | None:
    if derive_relation_kind(source_type, target_type) is not None:
        return None
    return f"不支持连线：{source_type} → {target_type}。章节顺序由 sort_order 表达。"


def validate_hierarchy_structure(db, work_id: str, source, target) -> str | None:
    if source.id == target.id:
        return "连线的两端不能是同一个节点"
    return validate_relation_types(source.type, target.type)
