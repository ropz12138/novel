"""章节短剧接口与智能体内部输入契约；权威数据由服务器保存。"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ShotRole(StrictModel):
    roleId: str = Field(min_length=1)
    portraitId: str | None = None


class StoryboardShot(StrictModel):
    id: str = Field(min_length=1)
    title: str = ''
    prompt: str = ''
    duration: float = Field(default=5, ge=1, le=15)
    seed: int = Field(default=42, ge=0)
    mode: Literal['turbo', 'base'] = 'turbo'
    inputMode: Literal['text', 'reference', 'first_lock'] = 'text'
    roles: list[ShotRole] = Field(default_factory=list)
    sourceQuote: str = ''
    sourceStartLine: int | None = Field(default=None, ge=1)
    sourceEndLine: int | None = Field(default=None, ge=1)
    referencePaths: str = ''
    firstFrame: str = ''
    lastFrame: str = ''
    firstFrameShotId: str = ''


class ConversationMessage(StrictModel):
    role: Literal['user', 'assistant', 'tool_call', 'tool_result', 'process', 'error']
    content: str
    reasoning: str = ''
    tool_name: str = ''
    tool_call_id: str | None = None
    arguments: str = ''


class StoredPortrait(StrictModel):
    id: str = Field(min_length=1)
    roleId: str = Field(min_length=1)
    imagePath: str = ''
    prompt: str = ''


class WorkspaceUpdate(StrictModel):
    sourceContent: str
    width: int = Field(default=960, ge=256, le=1280, multiple_of=16)
    height: int = Field(default=544, ge=256, le=1280, multiple_of=16)
    style: str = ''
    revision: int = Field(ge=0)
    activeSessionId: str | None = None
    shots: list[StoryboardShot] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_shots(self):
        if len({s.id for s in self.shots}) != len(self.shots):
            raise ValueError('镜头 ID 需要唯一')
        return self


class SessionCreate(StrictModel):
    title: str = Field(default='新对话', min_length=1, max_length=200)


class VideoCreate(StrictModel):
    shot_ids: list[str] = Field(min_length=1)
    quality: Literal['preview', 'final'] = 'final'


class StoryboardChatInput(StrictModel):
    message: str = Field(min_length=1)
    source_content: str
    session_id: str = Field(min_length=1)
    selected_shot_id: str | None = None

    @model_validator(mode='after')
    def nonempty_message(self):
        if not self.message.strip():
            raise ValueError('消息不能为空')
        return self


class PortraitBoardUpdate(StrictModel):
    revision: int = Field(ge=0)
    portraits: list[StoredPortrait] = Field(default_factory=list)

    @model_validator(mode='after')
    def unique_portraits(self):
        if len({item.id for item in self.portraits}) != len(self.portraits):
            raise ValueError('立绘 ID 需要唯一')
        return self


class StoryboardChatRequest(StrictModel):
    message: str = Field(min_length=1)
    source_content: str
    session_id: str = Field(min_length=1)
    shots: list[StoryboardShot] = Field(default_factory=list)
    history: list[ConversationMessage] = Field(default_factory=list)
    style: str = ''
    width: int = Field(default=960, ge=256, le=1280, multiple_of=16)
    height: int = Field(default=544, ge=256, le=1280, multiple_of=16)
    selected_shot_id: str | None = None

    @model_validator(mode='after')
    def valid_request(self):
        if not self.message.strip():
            raise ValueError('消息不能为空')
        ids = [shot.id for shot in self.shots]
        if len(ids) != len(set(ids)):
            raise ValueError('镜头 ID 需要唯一')
        if self.selected_shot_id is not None and self.selected_shot_id not in ids:
            raise ValueError('当前镜头需要属于本次分镜清单')
        return self


class DesignedShot(StrictModel):
    id: str | None = Field(default=None, description='更新现有镜头时填写其 ID；新增镜头填写 null')
    title: str = Field(min_length=1, description='便于用户识别的镜头名称')
    prompt: str = Field(min_length=1, description='可直接传给视频生成脚本的完整提示词，覆盖人物外观、场景、可见动作、景别、运镜、对白和声音')
    duration: float = Field(ge=1, le=15, description='本镜头目标秒数，按动作和对白的实际容量安排')
    roles: list[ShotRole] = Field(default_factory=list, description='出场角色。portraitId 填写该角色的一张立绘，null 表示只关联角色')
    firstFrameShotId: str | None = Field(description='首帧锁定的来源镜头 ID。填写排在本镜之前的镜头 ID；null 表示不锁定首帧')


class ReadStoryboard(StrictModel):
    shot_ids: list[str] | None = None


class RevisionInput(StrictModel):
    expected_revision: int = Field(ge=0)


class ReplaceStoryboard(RevisionInput):
    shots: list[DesignedShot] = Field(min_length=1)


class InsertShots(RevisionInput):
    after_shot_id: str | None
    shots: list[DesignedShot] = Field(min_length=1)


class ShotUpdate(StrictModel):
    id: str = Field(min_length=1)
    title: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    duration: float | None = Field(default=None, ge=1, le=15)
    roles: list[ShotRole] | None = None
    firstFrameShotId: str | None = Field(default=None, description='首帧锁定的来源镜头 ID。填写排在本镜之前的镜头 ID；null 表示取消首帧锁定。未提交时保留原选择')

    @model_validator(mode='after')
    def changed_fields(self):
        changed = self.model_fields_set - {'id'}
        if not changed or any(getattr(self, field) is None for field in changed - {'firstFrameShotId'}):
            raise ValueError('修改项需要提供至少一个字段，清空角色关联使用空列表')
        return self


class UpdateShots(RevisionInput):
    updates: list[ShotUpdate] = Field(min_length=1)


class ShotIdsInput(RevisionInput):
    shot_ids: list[str] = Field(min_length=1)


class ReadPortraits(StrictModel):
    portrait_ids: list[str] | None = None


class NewPortrait(StrictModel):
    roleId: str = Field(min_length=1, description='角色节点 ID')
    prompt: str = Field(min_length=1, description='这张立绘的完整提示词')


class InsertPortraits(RevisionInput):
    portraits: list[NewPortrait] = Field(min_length=1)


class PortraitUpdate(StrictModel):
    id: str = Field(min_length=1)
    prompt: str | None = Field(default=None, min_length=1)

    @model_validator(mode='after')
    def changed_fields(self):
        changed = self.model_fields_set - {'id'}
        if not changed or any(getattr(self, field) is None for field in changed):
            raise ValueError('修改项需要提供提示词')
        return self


class UpdatePortraits(RevisionInput):
    updates: list[PortraitUpdate] = Field(min_length=1)


class PortraitIdsInput(RevisionInput):
    portrait_ids: list[str] = Field(min_length=1)


class FinishStoryboardTurn(StrictModel):
    message: str = Field(min_length=1, description='根据工具回执说明实际完成范围、镜头数量和总时长；未完成内容明确交代')

    @model_validator(mode='after')
    def valid_message(self):
        if not self.message.strip():
            raise ValueError('最终回复需要包含有效内容')
        return self


class PortraitGenerate(StrictModel):
    width: int = Field(default=768, ge=256, le=2048, multiple_of=16)
    height: int = Field(default=1024, ge=256, le=2048, multiple_of=16)
    seed: int = Field(default=42, ge=0, le=4294967295)
