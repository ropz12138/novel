from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class EdgeCreate(BaseModel):
    source_id: str = Field(..., min_length=1, max_length=36)
    target_id: str = Field(..., min_length=1, max_length=36)
    edge_type: str = Field("uses", min_length=1, max_length=100)
    label: str = ""
    extra_data: dict = {}


class EdgeUpdate(BaseModel):
    edge_type: Optional[str] = Field(None, min_length=1, max_length=100)
    label: Optional[str] = None
    extra_data: Optional[dict] = None


class EdgeResponse(BaseModel):
    id: str
    source_id: str
    target_id: str
    edge_type: str
    label: str
    extra_data: dict
    created_at: datetime

    class Config:
        from_attributes = True


class EdgeListResponse(BaseModel):
    edges: list[EdgeResponse]
    total: int
