"""作品路由"""
import base64

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.work import CanvasWork
from app.models.node import Node
from app.models.edge import Edge
from app.models.user import User
from app.schemas.work import WorkCreate, WorkUpdate, WorkOut, WorkListOut
from app.schemas.canvas_snapshot import CanvasSnapshot, CanvasRestoreResponse, CanvasRenderUpload
from app.services.canvas_restore_service import apply_canvas_snapshot
from app.services.agents.tools import canvas_evaluate
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


@router.post("/{work_id}/canvas/render")
def upload_canvas_render(
    work_id: str,
    payload: CanvasRenderUpload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """接收前端上传的画布截图(base64)，落盘缓存供多模态评估工具读取"""
    work = db.query(CanvasWork).filter(
        CanvasWork.id == work_id,
        CanvasWork.user_id == current_user.id,
    ).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    path = canvas_evaluate.get_render_path(work_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(payload.image))
    return {"success": True}
