from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.controllers.character_controller import (
    create_character,
    delete_character,
    list_characters,
    update_character,
)
from app.models.work_model import User
from app.schemas.rpc_schema import (
    CharacterCreateRpcRequest,
    CharacterIdRpcRequest,
    CharacterListRpcRequest,
    CharacterUpdateRpcRequest,
    OkResponse,
)
from app.schemas.work_schema import CharacterCreateRequest, CharacterOut, CharacterUpdateRequest

router = APIRouter(prefix="/works/characters", tags=["characters"])


@router.post("/list", response_model=list[CharacterOut])
def list_characters_api(
    payload: CharacterListRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_characters(payload.work_id, db, payload.role_type, user_id=current_user.id)


@router.post("/create", response_model=CharacterOut, status_code=201)
def create_character_api(
    payload: CharacterCreateRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = CharacterCreateRequest.model_validate(
        payload.model_dump(exclude={"work_id"})
    )
    return create_character(payload.work_id, body, db, user_id=current_user.id)


@router.post("/update", response_model=CharacterOut)
def update_character_api(
    payload: CharacterUpdateRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    body = CharacterUpdateRequest.model_validate(
        payload.model_dump(exclude={"work_id", "character_id"})
    )
    return update_character(
        payload.work_id, payload.character_id, body, db, user_id=current_user.id
    )


@router.post("/delete", response_model=OkResponse)
def delete_character_api(
    payload: CharacterIdRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    delete_character(payload.work_id, payload.character_id, db, user_id=current_user.id)
    return OkResponse()
