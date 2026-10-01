"""当前用户相关：可用模型列表 + 主备模型偏好。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.user import User
from routers.auth import get_current_user, require_admin
from schemas.me import (
    ChapterReviewIntensityResponse,
    ChapterReviewIntensityUpdate,
    ModelsResponse,
    ModelPrefResponse,
    ModelPrefUpdate,
)
from services.chapter_review_preference import (
    save_chapter_review_intensity,
    get_saved_chapter_review_intensity,
)

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/models", response_model=ModelsResponse)
def get_models(current_user: User = Depends(require_admin)):
    """返回所有可用模型 + 全局默认主/备（供前端下拉选项）"""
    return ModelsResponse(
        available_models=settings.available_models,
        default_primary=settings.default_model,
        default_fallback=settings.fallback_model or None,
    )


def _validate_pref(primary, fallback):
    available = set(settings.available_models)
    for name in (primary, fallback):
        if name not in (None, "") and name not in available:
            raise HTTPException(status_code=400, detail=f"未知模型: {name}")
    if primary and fallback and primary == fallback:
        raise HTTPException(status_code=400, detail="主模型与备模型不能相同")


@router.get("/model-pref", response_model=ModelPrefResponse)
def get_model_pref(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """读取当前用户的主/备模型偏好（未设为 null）"""
    u = db.query(User).filter_by(id=current_user.id).first()
    return ModelPrefResponse(primary=u.primary_model, fallback=u.fallback_model)


@router.put("/model-pref", response_model=ModelPrefResponse)
def put_model_pref(
    payload: ModelPrefUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新主/备模型偏好；备用模型 null 表示默认，空字符串表示禁用。"""
    _validate_pref(payload.primary, payload.fallback)
    u = db.query(User).filter_by(id=current_user.id).first()
    u.primary_model = payload.primary
    u.fallback_model = payload.fallback
    db.commit()
    db.refresh(u)
    return ModelPrefResponse(primary=u.primary_model, fallback=u.fallback_model)


@router.get("/chapter-review-intensity", response_model=ChapterReviewIntensityResponse)
def get_chapter_review_intensity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """读取当前用户已保存的章节评审强度。"""
    try:
        intensity = get_saved_chapter_review_intensity(db, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChapterReviewIntensityResponse(chapter_review_intensity=intensity)


@router.put("/chapter-review-intensity", response_model=ChapterReviewIntensityResponse)
def put_chapter_review_intensity(
    payload: ChapterReviewIntensityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """保存当前用户选择的章节评审强度。"""
    try:
        intensity = save_chapter_review_intensity(
            db, current_user.id, payload.chapter_review_intensity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChapterReviewIntensityResponse(chapter_review_intensity=intensity)
