from sqlalchemy.orm import Session

from app.schemas.work_schema import (
    CharacterCreateRequest,
    CharacterOut,
    CharacterUpdateRequest,
)
from app.services.character_service import CharacterService

service = CharacterService()


def list_characters(work_id: str, db: Session, role_type: str | None = None, *, user_id: str) -> list[CharacterOut]:
    return service.list_characters(work_id, db, role_type, user_id=user_id)


def create_character(work_id: str, payload: CharacterCreateRequest, db: Session, *, user_id: str) -> CharacterOut:
    return service.create_character(work_id, payload, db, user_id=user_id)


def update_character(work_id: str, character_id: str, payload: CharacterUpdateRequest, db: Session, *, user_id: str) -> CharacterOut:
    return service.update_character(work_id, character_id, payload, db, user_id=user_id)


def delete_character(work_id: str, character_id: str, db: Session, *, user_id: str) -> None:
    service.delete_character(work_id, character_id, db, user_id=user_id)
