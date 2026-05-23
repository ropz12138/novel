from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.work_model import User, Work
from app.schemas.evaluation_schema import ChapterEvaluationRequest, ChapterEvaluationResponse
from app.services.evaluation_agent import EvaluationAgent

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.post("/works/{work_id}/chapters/{chapter_number}", response_model=ChapterEvaluationResponse)
async def evaluate_chapter(
    work_id: str,
    chapter_number: int,
    payload: ChapterEvaluationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    work = db.query(Work).filter_by(id=work_id, user_id=current_user.id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")

    agent = EvaluationAgent()
    try:
        chapter_title, editor, reader, sync = await agent.evaluate_chapter(
            db=db,
            work_id=work_id,
            chapter_number=chapter_number,
            chapter_content_override=payload.chapter_content,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"评估失败: {exc}") from exc

    return ChapterEvaluationResponse(
        work_id=work_id,
        chapter_number=chapter_number,
        chapter_title=chapter_title,
        editor=editor,
        reader=reader,
        sync=sync,
    )
