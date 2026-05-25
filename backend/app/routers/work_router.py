import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.controllers.work_controller import (
    chat_edit,
    chapter_chat_edit,
    delete_work,
    delete_last_chapter,
    generate_chapter,
    get_chapter_intel,
    generate_outline,
    get_chapter,
    get_work,
    list_chapters,
    list_works,
    update_chapter,
    update_outline,
)
from app.models.work_model import User
from app.schemas.work_schema import (
    ChapterChatRequest,
    ChapterChatResponse,
    ChapterGenerateResponse,
    ChapterDeleteLastResponse,
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

router = APIRouter(prefix="/works", tags=["works"])


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/generate-outline", response_model=OutlineGenerateResponse)
def generate_outline_api(
    payload: OutlineQuickGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return generate_outline(payload, db, user_id=current_user.id)


@router.post("/generate-outline-stream")
async def generate_outline_stream_api(
    payload: OutlineQuickGenerateRequest,
    current_user: User = Depends(get_current_user),
):
    """Stream outline generation via SSE. Events: outline_stream, outline_done, error."""
    from app.services.work_service import WorkService

    service = WorkService()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: str, data: dict):
        queue.put_nowait((event, data))

    async def event_generator():
        async def run():
            try:
                await service.generate_outline_stream(payload, emit, user_id=current_user.id)
            except Exception as exc:
                emit("error", {"message": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())

        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield _sse_format(event, data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("", response_model=list[WorkOut])
def list_works_api(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_works(db, user_id=current_user.id)


@router.get("/{work_id}", response_model=WorkOut)
def get_work_api(
    work_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_work(work_id, db, user_id=current_user.id)


@router.put("/{work_id}/outline", response_model=WorkOut)
def update_outline_api(
    work_id: str,
    payload: OutlineUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return update_outline(work_id, payload, db, user_id=current_user.id)


@router.post("/{work_id}/chat", response_model=ChatEditResponse)
def chat_edit_api(
    work_id: str,
    payload: ChatEditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return chat_edit(work_id, payload, db, user_id=current_user.id)


@router.delete("/{work_id}", status_code=204)
def delete_work_api(
    work_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    delete_work(work_id, db, user_id=current_user.id)


@router.get("/{work_id}/chapters", response_model=list[ChapterOut])
def list_chapters_api(
    work_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_chapters(work_id, db, user_id=current_user.id)


@router.get("/{work_id}/chapters/{chapter_number}", response_model=ChapterOut)
def get_chapter_api(
    work_id: str,
    chapter_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_chapter(work_id, chapter_number, db, user_id=current_user.id)


@router.get("/{work_id}/chapters/{chapter_number}/intel", response_model=ChapterIntelOut)
def get_chapter_intel_api(
    work_id: str,
    chapter_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_chapter_intel(work_id, chapter_number, db, user_id=current_user.id)


@router.delete("/{work_id}/chapters/last", response_model=ChapterDeleteLastResponse)
def delete_last_chapter_api(
    work_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return delete_last_chapter(work_id, db, user_id=current_user.id)


@router.post("/{work_id}/chapters/{chapter_number}/generate", response_model=ChapterGenerateResponse)
def generate_chapter_api(
    work_id: str,
    chapter_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return generate_chapter(work_id, chapter_number, db, user_id=current_user.id)


@router.post("/{work_id}/chapters/{chapter_number}/chat", response_model=ChapterChatResponse)
def chapter_chat_edit_api(
    work_id: str,
    chapter_number: int,
    payload: ChapterChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return chapter_chat_edit(work_id, chapter_number, payload, db, user_id=current_user.id)


@router.put("/{work_id}/chapters/{chapter_number}", response_model=ChapterOut)
def update_chapter_api(
    work_id: str,
    chapter_number: int,
    payload: ChapterUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return update_chapter(work_id, chapter_number, payload, db, user_id=current_user.id)
