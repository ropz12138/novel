from pydantic import BaseModel, Field


class ChapterEvaluationRequest(BaseModel):
    """Evaluate a chapter from editor and reader perspectives."""

    chapter_content: str = Field(
        default="",
        description="可选：传入正文将优先使用该内容；为空时读取数据库章节正文",
        max_length=120000,
    )


class RoleEvaluation(BaseModel):
    total_score: int = Field(description="总分（0-60）")
    scores: dict[str, int] = Field(default_factory=dict, description="分项得分，每项 1-10")
    strengths: list[str] = Field(default_factory=list, description="优点")
    issues: list[str] = Field(default_factory=list, description="问题")
    suggestions: list[str] = Field(default_factory=list, description="改进建议")


class SyncFinding(BaseModel):
    outline_ref: str = Field(default="", description="对应大纲位置")
    chapter_ref: str = Field(default="", description="对应正文证据")
    type: str = Field(default="", description="不一致类型：缺失/延后/提前/偏移/冲突")
    severity: str = Field(default="low", description="严重程度：low/medium/high")
    reason: str = Field(default="", description="原因说明")


class SyncEvaluation(BaseModel):
    sync_score: int = Field(default=0, description="同步分数 0-100")
    status: str = Field(default="partial_mismatch", description="aligned/partial_mismatch/major_mismatch")
    findings: list[SyncFinding] = Field(default_factory=list, description="不同步点")
    suggestions: list[str] = Field(default_factory=list, description="修复建议")
    next_chapter_watchlist: list[str] = Field(default_factory=list, description="下一章对齐检查点")
    action_hint: str = Field(default="fix_chapter", description="fix_chapter/fix_outline/fix_both/none")


class ChapterEvaluationResponse(BaseModel):
    work_id: str
    chapter_number: int
    chapter_title: str
    editor: RoleEvaluation
    reader: RoleEvaluation
    sync: SyncEvaluation = Field(default_factory=SyncEvaluation)
