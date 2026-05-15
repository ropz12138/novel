"""Schemas for supervisor session API responses."""
from datetime import datetime

from pydantic import BaseModel, Field


class SupervisorSessionOut(BaseModel):
    id: str
    work_id: str | None = None
    type: str = "supervisor"
    title: str
    stage: str
    status: str
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
