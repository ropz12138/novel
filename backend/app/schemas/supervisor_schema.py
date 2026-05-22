from pydantic import BaseModel, Field


# DEPRECATED: IntentResult 已不再被新架构使用，保留仅供参考


class SupervisorStartRequest(BaseModel):
    """Start a new supervisor session."""
    message: str = Field(description="用户消息")
    work_id: str | None = Field(default=None, description="关联作品ID（可选）")
    auto_mode: bool = Field(default=True, description="自动模式：所有编辑操作直接执行，不等待确认")


class SupervisorResumeRequest(BaseModel):
    """Resume an existing supervisor session."""
    session_id: str = Field(description="会话ID")
    message: str = Field(description="用户消息")


class IntentResult(BaseModel):
    """意图分类结果"""
    intent: str = Field(description="create_outline / edit_outline / write_chapter / edit_chapter / composite / chat")
    params: dict = Field(default_factory=dict, description="意图参数，如 idea, tags, chapter_number, work_id 等")
    reasoning: str = Field(default="", description="分类理由")
    steps: list[dict] = Field(default_factory=list, description="复合意图的步骤列表，每项含 intent 和 params")


class SupervisorConfirmRequest(BaseModel):
    """Confirm or reject a pending action."""
    session_id: str = Field(description="会话ID")
    action: str = Field(description="accept / reject")
    # For edit_chapter: user may optionally provide modified new_content
    new_content: str | None = Field(default=None, description="用户修改后的正文（可选，不传则使用 Agent 生成的版本）")
