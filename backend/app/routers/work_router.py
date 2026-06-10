import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.controllers.work_controller import (
    delete_work,
    delete_last_chapter,
    get_chapter_intel,
    get_work,
    list_chapters,
    list_works,
    update_chapter,
    update_outline,
    update_requirements_doc,
    update_meso_doc,
    update_micro_doc,
)
from app.models.work_model import User, Work
from app.schemas.rpc_schema import (
    ChapterNumberRequest,
    ChapterUpdateRpcRequest,
    OkResponse,
    OutlineDocUpdateRpcRequest,
    RequirementsDocUpdateRpcRequest,
    WorkIdRequest,
    WorkOutlineUpdateRpcRequest,
)
from app.schemas.work_schema import (
    ChapterDeleteLastResponse,
    ChapterIntelOut,
    ChapterOut,
    OutlineQuickGenerateRequest,
    WorkOut,
)

router = APIRouter(prefix="/works", tags=["works"])


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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


@router.post("/list", response_model=list[WorkOut])
def list_works_api(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_works(db, user_id=current_user.id)


@router.post("/get", response_model=WorkOut)
def get_work_api(
    payload: WorkIdRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_work(payload.work_id, db, user_id=current_user.id)


@router.post("/update-outline", response_model=WorkOut)
def update_outline_api(
    payload: WorkOutlineUpdateRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.schemas.work_schema import OutlineUpdateRequest

    return update_outline(
        payload.work_id,
        OutlineUpdateRequest(outline_tree=payload.outline_tree),
        db,
        user_id=current_user.id,
    )


@router.post("/delete", response_model=OkResponse)
def delete_work_api(
    payload: WorkIdRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    delete_work(payload.work_id, db, user_id=current_user.id)
    return OkResponse()


@router.post("/chapters/list", response_model=list[ChapterOut])
def list_chapters_api(
    payload: WorkIdRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_chapters(payload.work_id, db, user_id=current_user.id)


@router.post("/chapters/intel", response_model=ChapterIntelOut)
def get_chapter_intel_api(
    payload: ChapterNumberRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_chapter_intel(payload.work_id, payload.chapter_number, db, user_id=current_user.id)


@router.post("/chapters/delete-last", response_model=ChapterDeleteLastResponse)
def delete_last_chapter_api(
    payload: WorkIdRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return delete_last_chapter(payload.work_id, db, user_id=current_user.id)


@router.post("/chapters/update", response_model=ChapterOut)
def update_chapter_api(
    payload: ChapterUpdateRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.schemas.work_schema import ChapterUpdateRequest

    return update_chapter(
        payload.work_id,
        payload.chapter_number,
        ChapterUpdateRequest(title=payload.title, content=payload.content),
        db,
        user_id=current_user.id,
    )


@router.post("/requirements-doc/get")
def get_requirements_doc_api(
    payload: WorkIdRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = db.query(User).filter_by(id=current_user.id).first()
    if not user:
        raise HTTPException(status_code=401, detail="未登录")

    work = db.query(Work).filter_by(id=payload.work_id, user_id=current_user.id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")

    return {"content": work.requirements_doc or ""}


@router.post("/requirements-doc/update")
def update_requirements_doc_api(
    payload: RequirementsDocUpdateRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return update_requirements_doc(
        payload.work_id,
        payload.content,
        db,
        user_id=current_user.id,
    )


@router.post("/meso-doc/get")
def get_meso_doc_api(
    payload: WorkIdRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = db.query(User).filter_by(id=current_user.id).first()
    if not user:
        raise HTTPException(status_code=401, detail="未登录")

    work = db.query(Work).filter_by(id=payload.work_id, user_id=current_user.id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")

    return {"content": work.meso_doc or ""}


@router.post("/meso-doc/update")
def update_meso_doc_api(
    payload: OutlineDocUpdateRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return update_meso_doc(
        payload.work_id,
        payload.content,
        db,
        user_id=current_user.id,
    )


@router.post("/micro-doc/get")
def get_micro_doc_api(
    payload: WorkIdRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = db.query(User).filter_by(id=current_user.id).first()
    if not user:
        raise HTTPException(status_code=401, detail="未登录")

    work = db.query(Work).filter_by(id=payload.work_id, user_id=current_user.id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")

    return {"content": work.micro_doc or ""}


@router.post("/micro-doc/update")
def update_micro_doc_api(
    payload: OutlineDocUpdateRpcRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return update_micro_doc(
        payload.work_id,
        payload.content,
        db,
        user_id=current_user.id,
    )
