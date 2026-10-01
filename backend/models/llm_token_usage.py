"""每次 LLM 调用记一条 token 用量。"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LlmTokenUsage(Base):
    __tablename__ = "llm_token_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    work_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uncached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    time_to_first_token_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    generation_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    request_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
