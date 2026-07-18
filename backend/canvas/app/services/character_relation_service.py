"""角色关系线的校验与端点解析。"""
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.node import Node
from app.models.character_relation import CharacterRelation
from app.node_types import validate_character_relation, validate_relation_type


def find_relation_between_pair(
    db: Session,
    work_id: str,
    source_id: str,
    target_id: str,
) -> CharacterRelation | None:
    """查找同一对角色之间是否已有关系线（含反向）。"""
    return (
        db.query(CharacterRelation)
        .filter(
            CharacterRelation.work_id == work_id,
            or_(
                and_(
                    CharacterRelation.source_id == source_id,
                    CharacterRelation.target_id == target_id,
                ),
                and_(
                    CharacterRelation.source_id == target_id,
                    CharacterRelation.target_id == source_id,
                ),
            ),
        )
        .first()
    )


def format_pair_conflict_warning(
    existing: CharacterRelation,
    nodes_by_id: dict[str, Node],
    source: Node,
    target: Node,
) -> str:
    """生成自然语言警告：同一对角色已有关系，跳过创建。"""
    ex_src_title = nodes_by_id.get(existing.source_id, source).title
    ex_tgt_title = nodes_by_id.get(existing.target_id, target).title
    if existing.source_id not in nodes_by_id:
        ex_src_title = "?"
    if existing.target_id not in nodes_by_id:
        ex_tgt_title = "?"
    return (
        f"「{source.title}」与「{target.title}」之间已存在角色关系线"
        f"（{ex_src_title} → {ex_tgt_title}：{existing.relation_type}）。"
        f"同一对角色只能保留一条关系线，未创建新关系。"
        f"如需修改请使用 update_character_relation（关系 ID：{existing.id}）。"
    )


def resolve_relation_endpoints(
    db: Session,
    work_id: str,
    source_id: str,
    target_id: str,
) -> tuple[Node, Node] | str:
    if source_id == target_id:
        return "角色关系不能自环"

    source = db.query(Node).filter(Node.id == source_id, Node.work_id == work_id).first()
    if not source:
        return "源角色节点不存在"

    target = db.query(Node).filter(Node.id == target_id, Node.work_id == work_id).first()
    if not target:
        return "目标角色节点不存在"

    endpoint_err = validate_character_relation(source.type, target.type)
    if endpoint_err:
        return endpoint_err

    return source, target


def normalize_relation_type(relation_type: str) -> str | None:
    """校验并规范化 relation_type；非法时返回 None。"""
    try:
        return validate_relation_type(relation_type)
    except ValueError:
        return None
