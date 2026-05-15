from sqlalchemy.orm import Session

from app.schemas.work_schema import (
    ChapterChatRequest,
    ChapterChatResponse,
    ChapterGenerateResponse,
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


def generate_outline(payload: OutlineQuickGenerateRequest, db: Session) -> OutlineGenerateResponse:
    return service.generate_outline(payload, db)


def update_outline(work_id: str, payload: OutlineUpdateRequest, db: Session) -> WorkOut:
    return service.update_outline(work_id, payload.outline_tree, db)


def chat_edit(work_id: str, payload: ChatEditRequest, db: Session) -> ChatEditResponse:
    return service.chat_edit(work_id, payload.message, payload.history, db, session_id=payload.session_id)


def list_works(db: Session) -> list[WorkOut]:
    return service.list_works(db)


def get_work(work_id: str, db: Session) -> WorkOut:
    return service.get_work(work_id, db)


def delete_work(work_id: str, db: Session) -> None:
    service.delete_work(work_id, db)


def list_chapters(work_id: str, db: Session) -> list[ChapterOut]:
    return service.list_chapters(work_id, db)


def get_chapter(work_id: str, chapter_number: int, db: Session) -> ChapterOut:
    return service.get_chapter(work_id, chapter_number, db)


def generate_chapter(work_id: str, chapter_number: int, db: Session) -> ChapterGenerateResponse:
    return service.generate_chapter(work_id, chapter_number, db)


def update_chapter(work_id: str, chapter_number: int, payload: ChapterUpdateRequest, db: Session) -> ChapterOut:
    return service.update_chapter(work_id, chapter_number, payload, db)


def chapter_chat_edit(work_id: str, chapter_number: int, payload: ChapterChatRequest, db: Session) -> ChapterChatResponse:
    return service.chapter_chat_edit(work_id, chapter_number, payload.message, payload.history, db)
