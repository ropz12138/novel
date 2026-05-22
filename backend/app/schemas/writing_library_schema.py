from pydantic import BaseModel, Field


class ChapterSampleInput(BaseModel):
    chapter_ref: str = Field(description="章节定位，例如 第12章 或 vol1-ch12")
    title: str = Field(default="", description="章节标题")
    content: str = Field(description="章节正文样本")
    heat_score: float = Field(default=0.0, description="热度分，可选")


class WritingLibraryIngestRequest(BaseModel):
    source_site: str = Field(description="来源站点名")
    source_url: str = Field(description="来源URL")
    genre_tags: list[str] = Field(description="题材标签")
    chapter_samples: list[ChapterSampleInput] = Field(description="章节样本")
    credibility_score: float = Field(default=0.7, description="来源可信度分")


class WritingLibraryQueryRequest(BaseModel):
    problem_type: str = Field(description="问题类型")
    genre_tags: list[str] = Field(description="题材标签")
    constraints: list[str] = Field(default_factory=list, description="约束条件")
    top_k: int = Field(default=8, description="返回数量")
