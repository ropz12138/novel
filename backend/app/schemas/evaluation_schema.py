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


class ChapterEvaluationResponse(BaseModel):
    work_id: str
    chapter_number: int
    chapter_title: str
    editor: RoleEvaluation
    reader: RoleEvaluation
