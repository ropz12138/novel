from sqlalchemy.orm import Session

from app.schemas.work_schema import (
    ChapterChatRequest,
    ChapterChatResponse,
    ChapterGenerateResponse,
    ChapterIntelOut,
    ChapterOut,
    ChapterUpdateRequest,
    ChatEditRequest,
    ChatEditResponse,
    OutlineGenerateResponse,
    OutlineQuickGenerateRequest,
    OutlineUpdateRequest,
    WorkOut,
)
from app.services.work_service import WorkService

service = WorkService()


def generate_outline(payload: OutlineQuickGenerateRequest, db: Session, *, user_id: str) -> OutlineGenerateResponse:
    return service.generate_outline(payload, db, user_id=user_id)


def update_outline(work_id: str, payload: OutlineUpdateRequest, db: Session, *, user_id: str) -> WorkOut:
    return service.update_outline(work_id, payload.outline_tree, db, user_id=user_id)


def chat_edit(work_id: str, payload: ChatEditRequest, db: Session, *, user_id: str) -> ChatEditResponse:
    return service.chat_edit(work_id, payload.message, payload.history, db, session_id=payload.session_id, user_id=user_id)


def list_works(db: Session, *, user_id: str) -> list[WorkOut]:
    return service.list_works(user_id, db)


def get_work(work_id: str, db: Session, *, user_id: str) -> WorkOut:
    return service.get_work(work_id, user_id, db)


def delete_work(work_id: str, db: Session, *, user_id: str) -> None:
    service.delete_work(work_id, user_id, db)


def list_chapters(work_id: str, db: Session, *, user_id: str) -> list[ChapterOut]:
    return service.list_chapters(work_id, db, user_id=user_id)


def get_chapter(work_id: str, chapter_number: int, db: Session, *, user_id: str) -> ChapterOut:
    return service.get_chapter(work_id, chapter_number, db, user_id=user_id)


def generate_chapter(work_id: str, chapter_number: int, db: Session, *, user_id: str) -> ChapterGenerateResponse:
    return service.generate_chapter(work_id, chapter_number, db, user_id=user_id)


def update_chapter(work_id: str, chapter_number: int, payload: ChapterUpdateRequest, db: Session, *, user_id: str) -> ChapterOut:
    return service.update_chapter(work_id, chapter_number, payload, db, user_id=user_id)


def get_chapter_intel(work_id: str, chapter_number: int, db: Session, *, user_id: str) -> ChapterIntelOut:
    return service.get_chapter_intel(work_id, chapter_number, db, user_id=user_id)


def chapter_chat_edit(work_id: str, chapter_number: int, payload: ChapterChatRequest, db: Session, *, user_id: str) -> ChapterChatResponse:
    return service.chapter_chat_edit(work_id, chapter_number, payload.message, payload.history, db, user_id=user_id)
