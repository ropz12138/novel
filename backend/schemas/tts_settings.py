"""管理员可编辑的朗读参数，不包含模型连接信息。"""
from pydantic import BaseModel, ConfigDict, field_validator


class TtsStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: str


class TtsVoiceDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice_description: str

    @field_validator("voice_description")
    @classmethod
    def require_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("音色描述不能为空")
        return value


class TtsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mimo_tts: TtsStyle
    mimo_voicedesign: TtsVoiceDescription
