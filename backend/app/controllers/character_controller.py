from sqlalchemy.orm import Session

from app.schemas.work_schema import (
    CharacterCreateRequest,
    CharacterOut,
    CharacterUpdateRequest,
)
from app.services.character_service import CharacterService

service = CharacterService()


def list_characters(work_id: str, db: Session, role_type: str | None = None) -> list[CharacterOut]:
    return service.list_characters(work_id, db, role_type)


def get_character(work_id: str, character_id: str, db: Session) -> CharacterOut:
    return service.get_character(work_id, character_id, db)


def create_character(work_id: str, payload: CharacterCreateRequest, db: Session) -> CharacterOut:
    return service.create_character(work_id, payload, db)


def update_character(work_id: str, character_id: str, payload: CharacterUpdateRequest, db: Session) -> CharacterOut:
    return service.update_character(work_id, character_id, payload, db)


def delete_character(work_id: str, character_id: str, db: Session) -> None:
    service.delete_character(work_id, character_id, db)


def query_data(work_id: str, target: str, filters: dict, db: Session) -> list[dict]:
    return service.query_data(work_id, target, filters, db)


def grep(work_id: str, keyword: str, scope: str = "all", context_chars: int = 200, db: Session = None) -> list[dict]:
    return service.grep(work_id, keyword, scope, context_chars, db)
