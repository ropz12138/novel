from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CharacterRelationCreate(BaseModel):
    source_id: str = Field(..., min_length=1, max_length=36)
    target_id: str = Field(..., min_length=1, max_length=36)
    relation_type: str = Field(..., min_length=1, max_length=100)
    label: str = ""


class CharacterRelationUpdate(BaseModel):
    relation_type: Optional[str] = Field(None, min_length=1, max_length=100)
    label: Optional[str] = None


class CharacterRelationResponse(BaseModel):
    id: str
    work_id: str
    source_id: str
    target_id: str
    relation_type: str
    label: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CharacterRelationListResponse(BaseModel):
    relations: list[CharacterRelationResponse]
    total: int
