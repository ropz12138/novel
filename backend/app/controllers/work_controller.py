from sqlalchemy.orm import Session

from app.schemas.work_schema import (
    ChapterDeleteLastResponse,
    ChapterIntelOut,
    ChapterOut,
    ChapterUpdateRequest,
    OutlineUpdateRequest,
    WorkOut,
)
from app.services.work_service import WorkService

service = WorkService()


def update_outline(work_id: str, payload: OutlineUpdateRequest, db: Session, *, user_id: str) -> WorkOut:
    return service.update_outline(work_id, payload.outline_tree, db, user_id=user_id)


def list_works(db: Session, *, user_id: str) -> list[WorkOut]:
    return service.list_works(user_id, db)


def get_work(work_id: str, db: Session, *, user_id: str) -> WorkOut:
    return service.get_work(work_id, user_id, db)


def delete_work(work_id: str, db: Session, *, user_id: str) -> None:
    service.delete_work(work_id, user_id, db)


def list_chapters(work_id: str, db: Session, *, user_id: str) -> list[ChapterOut]:
    return service.list_chapters(work_id, db, user_id=user_id)


def update_chapter(work_id: str, chapter_number: int, payload: ChapterUpdateRequest, db: Session, *, user_id: str) -> ChapterOut:
    return service.update_chapter(work_id, chapter_number, payload, db, user_id=user_id)


def delete_last_chapter(work_id: str, db: Session, *, user_id: str) -> ChapterDeleteLastResponse:
    return service.delete_last_chapter(work_id, db, user_id=user_id)


def get_chapter_intel(work_id: str, chapter_number: int, db: Session, *, user_id: str) -> ChapterIntelOut:
    return service.get_chapter_intel(work_id, chapter_number, db, user_id=user_id)


def update_requirements_doc(work_id: str, content: str, db: Session, *, user_id: str) -> dict[str, str]:
    return service.update_requirements_doc(work_id, content, db, user_id=user_id)


def update_meso_doc(work_id: str, content: str, db: Session, *, user_id: str) -> dict[str, str]:
    return service.update_meso_doc(work_id, content, db, user_id=user_id)


def update_micro_doc(work_id: str, content: str, db: Session, *, user_id: str) -> dict[str, str]:
    return service.update_micro_doc(work_id, content, db, user_id=user_id)
