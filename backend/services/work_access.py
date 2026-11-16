"""Shared ownership check for work-scoped canvas operations."""
from fastapi import HTTPException

from models.work import CanvasWork


def require_work_owner(db, work_id: str, user_id: str) -> CanvasWork:
    work = db.query(CanvasWork).filter(
        CanvasWork.id == work_id, CanvasWork.user_id == user_id,
    ).first()
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return work
