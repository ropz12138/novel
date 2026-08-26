"""角色关系线 Agent 工具"""
import json
import asyncio
import logging
from functools import partial
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from models.node import Node
from models.character_relation import CharacterRelation
from services.character_relation_service import (
    resolve_relation_endpoints,
    normalize_relation_type,
    find_relation_between_pair,
    format_pair_conflict_warning,
)

logger = logging.getLogger(__name__)


def _get_db():
    from database import SessionLocal
    return SessionLocal()


def _get_current_work_id():
    try:
        from services.agents.supervisor import get_context
        return get_context().get("work_id")
    except Exception:
        return None


class QueryCharacterRelationsInput(BaseModel):
    character_name: Optional[str] = Field(default=None, description="按角色名筛选（可选）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class CreateCharacterRelationInput(BaseModel):
    source_id: str = Field(description="源角色节点 ID")
    target_id: str = Field(description="目标角色节点 ID")
    relation_type: str = Field(description="关系类型，自然语言描述，如「暗恋」「师徒」「世仇」")
    label: str = Field(default="", description="补充说明（可选）")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class UpdateCharacterRelationInput(BaseModel):
    relation_id: str = Field(description="角色关系 ID")
    relation_type: Optional[str] = Field(default=None, description="新的关系类型")
    label: Optional[str] = Field(default=None, description="新的补充说明")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class DeleteCharacterRelationInput(BaseModel):
    relation_id: str = Field(description="角色关系 ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


def _query_character_relations_sync(character_name=None, reason=None):
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    db = _get_db()
    try:
        q = db.query(CharacterRelation).filter(CharacterRelation.work_id == work_id)
        relations = q.order_by(CharacterRelation.created_at.asc()).all()
        if not relations:
            return "暂无角色关系线。"

        node_ids = {r.source_id for r in relations} | {r.target_id for r in relations}
        nodes = {
            n.id: n
            for n in db.query(Node).filter(Node.id.in_(node_ids)).all()
        }

        lines = []
        for rel in relations:
            src = nodes.get(rel.source_id)
            tgt = nodes.get(rel.target_id)
            if not src or not tgt:
                continue
            if character_name and character_name not in src.title and character_name not in tgt.title:
                continue
            label_part = f"（{rel.label}）" if rel.label else ""
            lines.append(
                f"- [{rel.id}] {src.title} → {tgt.title}：{rel.relation_type}{label_part}"
            )
        return "\n".join(lines) if lines else "未找到匹配的角色关系。"
    finally:
        db.close()


def _create_character_relation_sync(source_id, target_id, relation_type, label="", reason=None):
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    normalized = normalize_relation_type(relation_type)
    if normalized is None:
        return json.dumps({"error": "关系类型不能为空或超过100字符"}, ensure_ascii=False)

    db = _get_db()
    try:
        resolved = resolve_relation_endpoints(db, work_id, source_id, target_id)
        if isinstance(resolved, str):
            return json.dumps({"error": resolved}, ensure_ascii=False)
        source, target = resolved

        existing = find_relation_between_pair(db, work_id, source_id, target_id)
        if existing:
            warning = format_pair_conflict_warning(
                existing,
                {source.id: source, target.id: target},
                source,
                target,
            )
            return json.dumps({
                "success": False,
                "skipped": True,
                "warning": warning,
            }, ensure_ascii=False)

        relation = CharacterRelation(
            work_id=work_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=normalized,
            label=label or "",
        )
        db.add(relation)
        db.commit()
        db.refresh(relation)
        return json.dumps({
            "success": True,
            "relation": {
                "id": relation.id,
                "source_title": source.title,
                "target_title": target.title,
                "relation_type": relation.relation_type,
                "label": relation.label,
            },
        }, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _update_character_relation_sync(relation_id, relation_type=None, label=None, reason=None):
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    db = _get_db()
    try:
        relation = db.query(CharacterRelation).filter(
            CharacterRelation.id == relation_id,
            CharacterRelation.work_id == work_id,
        ).first()
        if not relation:
            return json.dumps({"error": "角色关系不存在"}, ensure_ascii=False)

        if relation_type is not None:
            normalized = normalize_relation_type(relation_type)
            if normalized is None:
                return json.dumps({"error": "关系类型不能为空或超过100字符"}, ensure_ascii=False)
            relation.relation_type = normalized
        if label is not None:
            relation.label = label

        db.commit()
        return json.dumps({"success": True, "relation_id": relation.id}, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


def _delete_character_relation_sync(relation_id, reason=None):
    work_id = _get_current_work_id()
    if not work_id:
        return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

    db = _get_db()
    try:
        relation = db.query(CharacterRelation).filter(
            CharacterRelation.id == relation_id,
            CharacterRelation.work_id == work_id,
        ).first()
        if not relation:
            return json.dumps({"error": "角色关系不存在"}, ensure_ascii=False)
        db.delete(relation)
        db.commit()
        return json.dumps({"success": True, "relation_id": relation_id}, ensure_ascii=False)
    except Exception as e:
        db.rollback()
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        db.close()


async def _query_character_relations_async(**kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_query_character_relations_sync, **kwargs))


async def _create_character_relation_async(**kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_create_character_relation_sync, **kwargs))


async def _update_character_relation_async(**kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_update_character_relation_sync, **kwargs))


async def _delete_character_relation_async(**kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_delete_character_relation_sync, **kwargs))


character_relation_tools = [
    StructuredTool.from_function(
        coroutine=_query_character_relations_async,
        name="query_character_relations",
        description="查询作品内角色之间的关系线（仅 character 节点之间）。可按角色名筛选。",
        args_schema=QueryCharacterRelationsInput,
    ),
    StructuredTool.from_function(
        coroutine=_create_character_relation_async,
        name="create_character_relation",
        description="创建角色关系线。两端必须是 character 节点；关系类型用自然语言描述；禁止自环。不要用 create_edge 连接两个角色。",
        args_schema=CreateCharacterRelationInput,
    ),
    StructuredTool.from_function(
        coroutine=_update_character_relation_async,
        name="update_character_relation",
        description="更新已有角色关系线的类型或补充说明。",
        args_schema=UpdateCharacterRelationInput,
    ),
    StructuredTool.from_function(
        coroutine=_delete_character_relation_async,
        name="delete_character_relation",
        description="删除一条角色关系线。",
        args_schema=DeleteCharacterRelationInput,
    ),
]
