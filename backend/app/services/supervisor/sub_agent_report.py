"""Structured reporting contract for sub agents."""

from pydantic import BaseModel, Field


class SubAgentReport(BaseModel):
    status: str = Field(default="completed", description="completed / failed / waiting")
    summary: str = Field(default="", description="一句话总结")
    actions: list[str] = Field(default_factory=list, description="关键动作")
    artifacts: list[str] = Field(default_factory=list, description="产出物")
    issues: list[str] = Field(default_factory=list, description="遗留问题")
    next_suggestions: list[str] = Field(default_factory=list, description="给 Supervisor 的后续建议")

    def to_result_summary(self) -> str:
        parts = [self.summary] if self.summary else []
        if self.actions:
            parts.append("关键动作：" + "；".join(self.actions))
        if self.issues:
            parts.append("遗留问题：" + "；".join(self.issues))
        return "\n".join(parts)
