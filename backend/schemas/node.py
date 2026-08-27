from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class NodeCreate(BaseModel):
    type: str = Field(..., min_length=1, max_length=30)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = ""
    extra_data: dict = {}
    layer: int = 0
    scope: Optional[str] = Field(None, description="作用域：global/local；不传则按类型推断（worldbuilding/note→global，其余→local）")
    position_x: float = 0.0
    position_y: float = 0.0


class NodeUpdate(BaseModel):
    type: Optional[str] = Field(None, min_length=1, max_length=30)
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = None
    extra_data: Optional[dict] = None
    layer: Optional[int] = None
    scope: Optional[str] = Field(None, description="新的作用域：global/local。worldbuilding/note 强制为 global")
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    locked: Optional[bool] = Field(None, description="是否固定节点（固定后坐标不可被 agent 修改）")
    chapter_elements: Optional[List[dict]] = Field(
        None,
        description="仅 chapter 节点：替换 extra_data.chapter_elements，保留 extra_data 中的其它字段",
    )
    storylines: Optional[List[dict]] = Field(
        None,
        description="仅 character 节点：替换 extra_data.storylines，保留 extra_data 中的其它字段",
    )


class NodeResponse(BaseModel):
    id: str
    type: str
    title: str
    content: str
    extra_data: dict
    layer: int
    scope: str
    position_x: float
    position_y: float
    locked: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class NodeListResponse(BaseModel):
    nodes: list[NodeResponse]
    total: int
