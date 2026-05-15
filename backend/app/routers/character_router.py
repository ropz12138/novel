from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.controllers.character_controller import (
    create_character,
    delete_character,
    get_character,
    grep,
    list_characters,
    query_data,
    update_character,
)
from app.schemas.work_schema import (
    CharacterCreateRequest,
    CharacterOut,
    CharacterUpdateRequest,
)

router = APIRouter(prefix="/works/{work_id}/characters", tags=["characters"])


@router.get("", response_model=list[CharacterOut])
def list_characters_api(
    work_id: str,
    role_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return list_characters(work_id, db, role_type)


@router.get("/{character_id}", response_model=CharacterOut)
def get_character_api(work_id: str, character_id: str, db: Session = Depends(get_db)):
    return get_character(work_id, character_id, db)


@router.post("", response_model=CharacterOut, status_code=201)
def create_character_api(
    work_id: str,
    payload: CharacterCreateRequest,
    db: Session = Depends(get_db),
):
    return create_character(work_id, payload, db)


@router.put("/{character_id}", response_model=CharacterOut)
def update_character_api(
    work_id: str,
    character_id: str,
    payload: CharacterUpdateRequest,
    db: Session = Depends(get_db),
):
    return update_character(work_id, character_id, payload, db)


@router.delete("/{character_id}", status_code=204)
def delete_character_api(work_id: str, character_id: str, db: Session = Depends(get_db)):
    delete_character(work_id, character_id, db)


@router.post("/tools/query")
def query_data_api(
    work_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    return query_data(work_id, payload.get("target", "characters"), payload.get("filters", {}), db)


@router.post("/tools/grep")
def grep_api(
    work_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    return grep(
        work_id,
        payload.get("keyword", ""),
        payload.get("scope", "all"),
        payload.get("context_chars", 200),
        db,
    )
