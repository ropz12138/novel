"""RPC-style POST request bodies (方案 A：动作路径 + JSON body)."""

from pydantic import BaseModel, Field

from app.schemas.work_schema import CharacterCreateRequest, CharacterUpdateRequest, ChapterUpdateRequest


class WorkIdRequest(BaseModel):
    work_id: str = Field(min_length=1)


class RequirementsDocUpdateRpcRequest(BaseModel):
    work_id: str = Field(min_length=1)
    content: str = ""


class OutlineDocUpdateRpcRequest(BaseModel):
    work_id: str = Field(min_length=1)
    content: str = ""


class WorkOutlineUpdateRpcRequest(BaseModel):
    work_id: str = Field(min_length=1)
    outline_tree: dict


class ChapterNumberRequest(BaseModel):
    work_id: str = Field(min_length=1)
    chapter_number: int = Field(ge=1)


class ChapterUpdateRpcRequest(ChapterUpdateRequest):
    work_id: str = Field(min_length=1)
    chapter_number: int = Field(ge=1)


class CharacterListRpcRequest(BaseModel):
    work_id: str = Field(min_length=1)
    role_type: str | None = None


class CharacterIdRpcRequest(BaseModel):
    work_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)


class CharacterCreateRpcRequest(CharacterCreateRequest):
    work_id: str = Field(min_length=1)


class CharacterUpdateRpcRequest(CharacterUpdateRequest):
    work_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)


class SupervisorSessionsListRpcRequest(BaseModel):
    work_id: str | None = None


class SessionIdRpcRequest(BaseModel):
    session_id: str = Field(min_length=1)


class OkResponse(BaseModel):
    ok: bool = True
