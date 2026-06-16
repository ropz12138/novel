from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class NodeCreate(BaseModel):
    type: str = Field(..., min_length=1, max_length=30)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = ""
    extra_data: dict = {}
    position_x: float = 0.0
    position_y: float = 0.0


class NodeUpdate(BaseModel):
    type: Optional[str] = Field(None, min_length=1, max_length=30)
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = None
    extra_data: Optional[dict] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None


class NodeResponse(BaseModel):
    id: str
    type: str
    title: str
    content: str
    extra_data: dict
    position_x: float
    position_y: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NodeListResponse(BaseModel):
    nodes: list[NodeResponse]
    total: int
