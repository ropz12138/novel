from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.controllers.work_controller import (
    chat_edit,
    chapter_chat_edit,
    delete_work,
    generate_chapter,
    generate_outline,
    get_chapter,
    get_work,
    list_chapters,
    list_works,
    update_chapter,
    update_outline,
)
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

router = APIRouter(prefix="/works", tags=["works"])


@router.post("/generate-outline", response_model=OutlineGenerateResponse)
def generate_outline_api(
    payload: OutlineQuickGenerateRequest,
    db: Session = Depends(get_db),
):
    return generate_outline(payload, db)


@router.get("", response_model=list[WorkOut])
def list_works_api(db: Session = Depends(get_db)):
    return list_works(db)


@router.get("/{work_id}", response_model=WorkOut)
def get_work_api(work_id: str, db: Session = Depends(get_db)):
    return get_work(work_id, db)


@router.put("/{work_id}/outline", response_model=WorkOut)
def update_outline_api(
    work_id: str,
    payload: OutlineUpdateRequest,
    db: Session = Depends(get_db),
):
    return update_outline(work_id, payload, db)


@router.post("/{work_id}/chat", response_model=ChatEditResponse)
def chat_edit_api(
    work_id: str,
    payload: ChatEditRequest,
    db: Session = Depends(get_db),
):
    return chat_edit(work_id, payload, db)


@router.delete("/{work_id}", status_code=204)
def delete_work_api(work_id: str, db: Session = Depends(get_db)):
    delete_work(work_id, db)


@router.get("/{work_id}/chapters", response_model=list[ChapterOut])
def list_chapters_api(work_id: str, db: Session = Depends(get_db)):
    return list_chapters(work_id, db)


@router.get("/{work_id}/chapters/{chapter_number}", response_model=ChapterOut)
def get_chapter_api(work_id: str, chapter_number: int, db: Session = Depends(get_db)):
    return get_chapter(work_id, chapter_number, db)


@router.post("/{work_id}/chapters/{chapter_number}/generate", response_model=ChapterGenerateResponse)
def generate_chapter_api(work_id: str, chapter_number: int, db: Session = Depends(get_db)):
    return generate_chapter(work_id, chapter_number, db)


@router.post("/{work_id}/chapters/{chapter_number}/chat", response_model=ChapterChatResponse)
def chapter_chat_edit_api(
    work_id: str,
    chapter_number: int,
    payload: ChapterChatRequest,
    db: Session = Depends(get_db),
):
    return chapter_chat_edit(work_id, chapter_number, payload, db)


@router.put("/{work_id}/chapters/{chapter_number}", response_model=ChapterOut)
def update_chapter_api(
    work_id: str,
    chapter_number: int,
    payload: ChapterUpdateRequest,
    db: Session = Depends(get_db),
):
    return update_chapter(work_id, chapter_number, payload, db)
