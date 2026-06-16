from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class ChapterResponse(BaseModel):
    node_id: str
    summary: str
    new_facts: list
    foreshadows: list
    generation_context: dict
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GenerateRequest(BaseModel):
    node_id: str
    extra_instructions: str = ""


class GenerateResponse(BaseModel):
    node_id: str
    content: str
    summary: str
    new_facts: list
    foreshadows: list
