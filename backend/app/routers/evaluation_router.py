from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.evaluation_schema import ChapterEvaluationRequest, ChapterEvaluationResponse
from app.services.evaluation_agent import EvaluationAgent

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.post("/works/{work_id}/chapters/{chapter_number}", response_model=ChapterEvaluationResponse)
async def evaluate_chapter(
    work_id: str,
    chapter_number: int,
    payload: ChapterEvaluationRequest,
    db: Session = Depends(get_db),
):
    agent = EvaluationAgent()
    try:
        chapter_title, editor, reader = await agent.evaluate_chapter(
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
    )
