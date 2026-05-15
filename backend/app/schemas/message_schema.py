"""Schemas for message-related API responses."""
from datetime import datetime

from pydantic import BaseModel


class MessageOut(BaseModel):
    id: str
    session_id: str
    work_id: str | None = None
    role: str
    content: str
    meta: dict | None = None
    sort_order: int
    created_at: datetime | str | None = None
