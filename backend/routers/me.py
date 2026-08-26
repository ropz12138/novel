"""当前用户相关：可用模型列表 + 主备模型偏好。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.user import User
from routers.auth import get_current_user
from schemas.me import ModelsResponse, ModelPrefResponse, ModelPrefUpdate

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/models", response_model=ModelsResponse)
def get_models(current_user: User = Depends(get_current_user)):
    """返回所有可用模型 + 全局默认主/备（供前端下拉选项）"""
    return ModelsResponse(
        available_models=settings.available_models,
        default_primary=settings.default_model,
        default_fallback=settings.fallback_model or None,
    )


def _validate_pref(primary, fallback):
    available = set(settings.available_models)
    for name in (primary, fallback):
        if name is not None and name not in available:
            raise HTTPException(status_code=400, detail=f"未知模型: {name}")
    if primary and fallback and primary == fallback:
        raise HTTPException(status_code=400, detail="主模型与备模型不能相同")


@router.get("/model-pref", response_model=ModelPrefResponse)
def get_model_pref(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """读取当前用户的主/备模型偏好（未设为 null）"""
    u = db.query(User).filter_by(id=current_user.id).first()
    return ModelPrefResponse(primary=u.primary_model, fallback=u.fallback_model)


@router.put("/model-pref", response_model=ModelPrefResponse)
def put_model_pref(
    payload: ModelPrefUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新当前用户的主/备模型偏好（全量替换，传 null 清空回退默认）"""
    _validate_pref(payload.primary, payload.fallback)
    u = db.query(User).filter_by(id=current_user.id).first()
    u.primary_model = payload.primary
    u.fallback_model = payload.fallback
    db.commit()
    db.refresh(u)
    return ModelPrefResponse(primary=u.primary_model, fallback=u.fallback_model)
