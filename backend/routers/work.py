"""作品路由"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.work import CanvasWork
from models.node import Node
from models.edge import Edge
from models.user import User
from schemas.work import WorkCreate, WorkOut, WorkListOut
from schemas.canvas_snapshot import CanvasSnapshot, CanvasRestoreResponse
from services.canvas_restore_service import apply_canvas_snapshot
from routers.auth import get_current_user

router = APIRouter(prefix="/works", tags=["works"])


@router.get("", response_model=WorkListOut)
def list_works(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的所有作品"""
    works = db.query(CanvasWork).filter(
        CanvasWork.user_id == current_user.id
    ).order_by(CanvasWork.updated_at.desc()).all()
    return WorkListOut(works=works)


@router.post("", response_model=WorkOut)
def create_work(
    data: WorkCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新作品"""
    work = CanvasWork(
        user_id=current_user.id,
        title=data.title,
        description=data.description,
    )
    db.add(work)
    db.commit()
    db.refresh(work)
    return work


@router.delete("/{work_id}")
def delete_work(
    work_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除作品"""
    work = db.query(CanvasWork).filter(
        CanvasWork.id == work_id,
        CanvasWork.user_id == current_user.id,
    ).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    
    db.delete(work)
    db.commit()
    return {"success": True}


@router.post("/{work_id}/canvas/restore", response_model=CanvasRestoreResponse)
def restore_canvas(
    work_id: str,
    snapshot: CanvasSnapshot,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将画布恢复到 snapshot 状态（用于 Ctrl+Z 撤回）"""
    work = db.query(CanvasWork).filter(
        CanvasWork.id == work_id,
        CanvasWork.user_id == current_user.id,
    ).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")

    return apply_canvas_snapshot(db, work_id, snapshot)
