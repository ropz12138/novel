from typing import Optional

from pydantic import BaseModel, Field


class ModelsResponse(BaseModel):
    available_models: list[str]
    default_primary: str
    default_fallback: Optional[str] = None


class ModelPrefResponse(BaseModel):
    primary: Optional[str] = None
    fallback: Optional[str] = None


class ModelPrefUpdate(BaseModel):
    primary: Optional[str] = Field(default=None, description="主模型名；null 表示回退全局默认")
    fallback: Optional[str] = Field(default=None, description="备模型名；null 表示回退全局默认")
