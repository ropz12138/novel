from pydantic import BaseModel, Field, field_validator

from app.node_types import validate_node_type


class SnapshotNode(BaseModel):
    id: str
    type: str
    title: str
    content: str = ""
    extra_data: dict = Field(default_factory=dict)
    layer: int = 0
    scope: str = "local"
    position_x: float = 0.0
    position_y: float = 0.0

    @field_validator("type")
    @classmethod
    def validate_type_value(cls, value: str) -> str:
        return validate_node_type(value)


class SnapshotEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    edge_type: str = "uses"
    label: str = ""
    extra_data: dict = Field(default_factory=dict)


class SnapshotCharacterRelation(BaseModel):
    id: str
    source_id: str
    target_id: str
    relation_type: str
    label: str = ""


class CanvasSnapshot(BaseModel):
    nodes: list[SnapshotNode] = Field(default_factory=list)
    edges: list[SnapshotEdge] = Field(default_factory=list)
    character_relations: list[SnapshotCharacterRelation] = Field(default_factory=list)


class CanvasRestoreResponse(BaseModel):
    success: bool
    node_count: int
    edge_count: int
    relation_count: int = 0


class CanvasRenderUpload(BaseModel):
    image: str = Field(..., description="base64 编码的画布 PNG 截图（前端 html-to-image 生成）")
