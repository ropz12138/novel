from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.character_relation import CharacterRelation
from models.work import CanvasWork
from models.user import User
from schemas.character_relation import (
    CharacterRelationCreate,
    CharacterRelationResponse,
    CharacterRelationListResponse,
)
from services.character_relation_service import (
    resolve_relation_endpoints,
    normalize_relation_type,
    find_relation_between_pair,
    format_pair_conflict_warning,
)
from routers.auth import get_current_user

router = APIRouter(tags=["character-relations"])


def _get_user_work(work_id: str, user: User, db: Session) -> CanvasWork:
    work = db.query(CanvasWork).filter(
        CanvasWork.id == work_id,
        CanvasWork.user_id == user.id,
    ).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    return work


@router.post(
    "/works/{work_id}/character-relations",
    response_model=CharacterRelationResponse,
    status_code=201,
)
def create_character_relation(
    work_id: str,
    data: CharacterRelationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_work(work_id, current_user, db)

    relation_type = normalize_relation_type(data.relation_type)
    if relation_type is None:
        raise HTTPException(status_code=400, detail="关系类型不能为空或超过100字符")

    resolved = resolve_relation_endpoints(db, work_id, data.source_id, data.target_id)
    if isinstance(resolved, str):
        raise HTTPException(status_code=400, detail=resolved)

    source, target = resolved

    existing = find_relation_between_pair(db, work_id, data.source_id, data.target_id)
    if existing:
        warning = format_pair_conflict_warning(
            existing,
            {source.id: source, target.id: target},
            source,
            target,
        )
        raise HTTPException(status_code=409, detail=warning)

    relation = CharacterRelation(
        work_id=work_id,
        source_id=data.source_id,
        target_id=data.target_id,
        relation_type=relation_type,
        label=data.label or "",
    )
    db.add(relation)
    db.commit()
    db.refresh(relation)
    return relation


@router.get(
    "/works/{work_id}/character-relations",
    response_model=CharacterRelationListResponse,
)
def list_character_relations(
    work_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_user_work(work_id, current_user, db)
    relations = (
        db.query(CharacterRelation)
        .filter(CharacterRelation.work_id == work_id)
        .order_by(CharacterRelation.created_at.asc())
        .all()
    )
    return CharacterRelationListResponse(relations=relations, total=len(relations))


@router.delete("/character-relations/{relation_id}", status_code=204)
def delete_character_relation(
    relation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    relation = db.query(CharacterRelation).filter(CharacterRelation.id == relation_id).first()
    if not relation:
        raise HTTPException(status_code=404, detail="角色关系不存在")
    _get_user_work(relation.work_id, current_user, db)
    db.delete(relation)
    db.commit()
