"""作品Schema"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class WorkCreate(BaseModel):
    title: str = Field(default="未命名作品", description="作品标题")
    description: str = Field(default="", description="作品描述")


class WorkUpdate(BaseModel):
    title: Optional[str] = Field(default=None, description="作品标题")
    description: Optional[str] = Field(default=None, description="作品描述")


class WorkOut(BaseModel):
    id: str
    user_id: str
    title: str
    description: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkListOut(BaseModel):
    works: list[WorkOut]
