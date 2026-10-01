from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from models.work import CanvasWork
from routers.auth import require_admin
from schemas.token_usage import TokenUsageResponse
from services.token_usage import series_token_usage, summarize_token_usage

router = APIRouter(prefix="/token-usage", tags=["token-usage"])


@router.get("", response_model=TokenUsageResponse)
def get_token_usage(
    work_id: str | None = None,
    grain: Literal["day", "hour"] = "day",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if work_id:
        owned = db.query(CanvasWork).filter_by(id=work_id, user_id=current_user.id).first()
        if owned is None:
            raise HTTPException(status_code=404, detail="作品不存在")
    works = (
        db.query(CanvasWork)
        .filter_by(user_id=current_user.id)
        .order_by(CanvasWork.title.asc(), CanvasWork.id.asc())
        .all()
    )
    return TokenUsageResponse(
        works=[{"id": work.id, "title": work.title} for work in works],
        models=summarize_token_usage(work_id),
        series=series_token_usage(work_id, grain),
    )
