"""用户章节评审强度：读取与保存都要求合法档位。"""
from sqlalchemy.orm import Session

from models.user import User

CHAPTER_REVIEW_INTENSITIES = ("low", "medium", "high")


def get_saved_chapter_review_intensity(db: Session, user_id: str) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise ValueError("用户不存在")
    value = user.chapter_review_intensity
    if value not in CHAPTER_REVIEW_INTENSITIES:
        raise ValueError(f"评审强度无效：{value}")
    return value


def save_chapter_review_intensity(db: Session, user_id: str, intensity: str) -> str:
    if intensity not in CHAPTER_REVIEW_INTENSITIES:
        raise ValueError(f"评审强度无效：{intensity}")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise ValueError("用户不存在")
    user.chapter_review_intensity = intensity
    db.commit()
    db.refresh(user)
    return user.chapter_review_intensity
