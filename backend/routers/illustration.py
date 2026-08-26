from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
from models.chapter_illustration import ChapterIllustration
from models.user import User
from models.work import CanvasWork
from routers.auth import get_current_user

router = APIRouter(tags=["illustrations"])


@router.get("/illustrations/{illustration_id}")
def get_illustration(
    illustration_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = db.query(ChapterIllustration).filter(
        ChapterIllustration.id == illustration_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="插图不存在")

    work = db.query(CanvasWork).filter(
        CanvasWork.id == row.work_id,
        CanvasWork.user_id == current_user.id,
    ).first()
    if not work:
        raise HTTPException(status_code=404, detail="插图不存在")

    path = Path(row.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="插图文件不存在")

    return FileResponse(path, media_type="image/png")
