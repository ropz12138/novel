"""作品路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.work import CanvasWork
from app.models.user import User
from app.schemas.work import WorkCreate, WorkUpdate, WorkOut, WorkListOut
from app.routers.auth import get_current_user

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


@router.get("/{work_id}", response_model=WorkOut)
def get_work(
    work_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取作品详情"""
    work = db.query(CanvasWork).filter(
        CanvasWork.id == work_id,
        CanvasWork.user_id == current_user.id,
    ).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    return work


@router.put("/{work_id}", response_model=WorkOut)
def update_work(
    work_id: str,
    data: WorkUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新作品"""
    work = db.query(CanvasWork).filter(
        CanvasWork.id == work_id,
        CanvasWork.user_id == current_user.id,
    ).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    
    if data.title is not None:
        work.title = data.title
    if data.description is not None:
        work.description = data.description
    
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
