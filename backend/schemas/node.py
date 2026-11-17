from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


SORT_ORDER_DESC = (
    "作品内同类型节点的显示顺序（必填，整数），按此值从小到大排列。"
    "章节顺序由它决定。请按叙事先后依次给出 1、2、3……"
)


class NodeCreate(BaseModel):
    type: str = Field(..., min_length=1, max_length=30)
    title: str = Field(..., min_length=1, max_length=200)
    content: str = ""
    extra_data: dict = {}
    layer: int = 0
    sort_order: int = Field(..., description=SORT_ORDER_DESC)
    scope: Optional[str] = Field(None, description="作用域：global/local；不传则按类型推断（worldbuilding/note/reviewer_note→global，其余→local）")
    position_x: float = 0.0
    position_y: float = 0.0


class NodeUpdate(BaseModel):
    type: Optional[str] = Field(None, min_length=1, max_length=30)
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = None
    expected_content: Optional[str] = Field(
        None,
        description="更新正文时的并发基线；若当前正文已变化则拒绝写入",
    )
    notes: Optional[str] = Field(None, description="仅 chapter 节点：章节笔记，支持 Markdown")
    extra_data: Optional[dict] = None
    layer: Optional[int] = None
    sort_order: Optional[int] = Field(None, description=f"新的{SORT_ORDER_DESC}")
    scope: Optional[str] = Field(None, description="新的作用域：global/local。worldbuilding/note/reviewer_note 强制为 global")
    position_x: Optional[float] = None
    position_y: Optional[float] = None
    locked: Optional[bool] = Field(None, description="是否固定节点（固定后坐标不可被 agent 修改）")
    characters: Optional[List[dict]] = Field(
        None,
        description=(
            "仅 chapter 节点：替换 extra_data.characters。"
            "每项必须含 id（character 节点 ID）与 name（角色名）"
        ),
    )
    storylines: Optional[List[dict]] = Field(
        None,
        description="仅 character 节点：替换 extra_data.storylines，保留 extra_data 中的其它字段",
    )


class NodeResponse(BaseModel):
    notes: str = ""
    id: str
    type: str
    title: str
    content: str
    extra_data: dict
    layer: int
    sort_order: int
    scope: str
    position_x: float
    position_y: float
    locked: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("extra_data", mode="before")
    @classmethod
    def drop_removed_extra_fields(cls, value):
        if isinstance(value, dict) and "chapter_elements" in value:
            value = {key: item for key, item in value.items() if key != "chapter_elements"}
        return value or {}

    class Config:
        from_attributes = True


class NodeListResponse(BaseModel):
    nodes: list[NodeResponse]
    total: int
