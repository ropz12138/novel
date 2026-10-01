import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="user", server_default=text("'user'"),
    )
    primary_model: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    fallback_model: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    chapter_review_intensity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium", server_default="medium",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
