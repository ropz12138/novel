from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class OutlineQuickGenerateRequest(BaseModel):
    idea: str = Field(min_length=1, max_length=500)
    tags: list[str] = Field(default_factory=list)


class StoryInfo(BaseModel):
    title: str
    genre: str
    volume: str


class TimelineNode(BaseModel):
    id: str
    order: int
    development_node: str
    time_node: str
    chapter_start: int
    chapter_end: int
    mainline: bool = True


class BranchNode(BaseModel):
    id: str
    name: str
    attach_to: str
    side: Literal["left", "right"]
    chapter_start: int
    chapter_end: int
    summary: str


class ForeshadowingNode(BaseModel):
    id: str
    plant_node: str
    payoff_node: str
    content: str


class OutlineTreeData(BaseModel):
    story: StoryInfo
    timeline: list[TimelineNode]
    branches: list[BranchNode]
    foreshadowing: list[ForeshadowingNode]


class OutlineGenerateResponse(BaseModel):
    outline_tree: OutlineTreeData
    work_id: str


class OutlineUpdateRequest(BaseModel):
    outline_tree: dict


class ChatEditRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    history: list[dict] = Field(default_factory=list)


class ToolCall(BaseModel):
    tool: str
    args: dict


class ChatEditResponse(BaseModel):
    assistant_message: str
    operations: list[ToolCall]
    outline_tree: dict


class WorkOut(BaseModel):
    id: str
    title: str
    genre: str
    idea: str
    tags: list[str]
    outline_tree: dict
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_tags(cls, data):
        if hasattr(data, "tags"):
            tags = data.tags
            if isinstance(tags, str):
                import json
                data.tags = json.loads(tags)
        return data


class ChapterOut(BaseModel):
    id: str
    work_id: str
    chapter_number: int
    title: str
    content: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChapterUpdateRequest(BaseModel):
    title: str | None = None
    content: str | None = None


class ChapterGenerateResponse(BaseModel):
    chapter: ChapterOut
    message: str = "正文生成成功"


class ChapterChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)


class ChapterChatResponse(BaseModel):
    assistant_message: str
    proposed_content: str
    proposed_title: str | None = None
