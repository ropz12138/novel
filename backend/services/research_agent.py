"""独立、可暂停恢复的长篇小说研究 Agent。"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import func

from models.research import (
    ResearchArtifact,
    ResearchContextEpoch,
    ResearchEvent,
    ResearchInstruction,
    ResearchJob,
    ResearchTextVersion,
)
from config import settings
from models.user import User
from services.agents.llm import bind_tools_to_llm, get_llm
from services.message_content_utils import extract_text_content, extract_tool_calls
from services import research_text_tools as text_tools


logger = logging.getLogger(__name__)
PROMPT_PATH = (
    Path(__file__).parent / "agents" / "prompts" / "research_system.txt"
)
RECENT_CONTEXT_CHAR_LIMIT = 1_500_000
CONTEXT_COMPACTION_THRESHOLD = 0.90
COMPACTION_OUTPUT_RESERVE_TOKENS = 12_000
CHARS_PER_ESTIMATED_TOKEN = 3
CONTEXT_ARCHIVE_SCHEMA_VERSION = 1
DEFAULT_RESEARCH_CONTEXT_WINDOW = 128_000


def _get_db():
    from database import SessionLocal
    return SessionLocal()


TextVersion = Literal["original", "active"]
InspectMode = Literal["head", "tail", "head_tail", "char_range", "evenly_spaced"]
SearchMode = Literal["literal", "regex"]
TransformOperation = Literal[
    "delete_line",
    "literal_replace",
    "regex_replace",
    "delete_between",
]
LineMatchMode = Literal["literal", "contains", "regex"]
ClassifierMode = Literal["regex_line", "regex_search"]
EditOperationName = Literal["replace", "delete", "insert_before", "insert_after"]
SectionReadMode = Literal["head", "tail", "head_tail", "full"]
WorkspaceWriteMode = Literal["create", "overwrite", "append"]


class InspectInput(BaseModel):
    version: str = Field(
        default="original",
        description="文本版本：original、active、v1 之类的版本号或版本ID",
    )
    encoding: str | None = Field(
        default=None,
        description="仅在需要覆盖自动编码识别时填写，例如 gb18030 或 utf-8",
    )
    mode: InspectMode = Field(
        default="evenly_spaced",
        description=(
            "采样方式：head=开头，tail=结尾，head_tail=首尾，"
            "char_range=从start开始，evenly_spaced=全书均匀采样"
        ),
    )
    window_chars: int = Field(default=1600, ge=200, le=8000)
    count: int = Field(
        default=10,
        ge=1,
        le=30,
        description="仅 evenly_spaced 模式会使用多个采样点",
    )
    start: int | None = Field(
        default=None,
        ge=0,
        description="char_range 模式的起始字符位置",
    )


class GrepInput(BaseModel):
    query: str = Field(description="要搜索的普通文本或正则表达式")
    version: str = Field(
        default="active",
        description="文本版本：active、original、v1 或版本ID",
    )
    mode: SearchMode = Field(
        default="literal",
        description="literal=按原文搜索；regex=按正则表达式搜索",
    )
    encoding: str | None = None
    context_before: int = Field(default=120, ge=0, le=2000)
    context_after: int = Field(default=200, ge=0, le=2000)
    limit: int = Field(default=30, ge=1, le=200)
    start_char: int = Field(default=0, ge=0)
    count_only: bool = False


class CreateCopyInput(BaseModel):
    source_version: str = Field(
        default="original",
        description="通常使用 original；也可使用 v1 或版本ID",
    )
    source_encoding: str | None = None
    normalize_newlines: bool = True
    strip_bom: bool = True


class TransformRule(BaseModel):
    id: str | None = Field(
        default=None,
        description="便于在预览报告中识别规则的可选名称",
    )
    operation: TransformOperation = Field(
        description=(
            "delete_line=删除匹配整行；literal_replace=普通文本替换；"
            "regex_replace=正则替换；delete_between=删除起止标记之间的内容"
        ),
    )
    pattern: str = Field(
        min_length=1,
        description="匹配文本或正则；delete_between 时表示起始标记",
    )
    match_mode: LineMatchMode = Field(
        default="literal",
        description=(
            "delete_line 的行匹配方式；delete_between 使用 literal 或 regex。"
            "替换操作无需修改此字段"
        ),
    )
    replacement: str = Field(
        default="",
        description=(
            "literal_replace/regex_replace 的替换文本。正则命名组可写 ${heading}"
        ),
    )
    end_pattern: str | None = Field(
        default=None,
        description="仅 delete_between 必填，表示结束标记或正则",
    )


class TransformInput(BaseModel):
    rules: list[TransformRule] = Field(
        min_length=1,
        max_length=100,
        description="由 Agent 根据实际噪点格式给出的确定性清理规则",
    )
    source_version: str = Field(
        default="active",
        description="待处理版本：active、v1 或版本ID；原始版不会被覆盖",
    )
    preview: bool = Field(
        default=True,
        description="必须先用 true 检查命中与样例，确认后才用 false 创建新版本",
    )


class SectionClassifier(BaseModel):
    name: str = Field(
        description="分类名称，例如 volume、chapter、extra；后续读取时使用同一名称",
    )
    pattern: str = Field(
        min_length=1,
        description=(
            "Python正则。建议使用命名组 (?P<number>...) 和 (?P<title>...)；"
            "例如 ^第(?P<number>[一二三四五六七八九十百千0-9]+)章(?P<title>.*)$"
        ),
    )
    mode: ClassifierMode = Field(
        default="regex_line",
        description="regex_line=从行首匹配；regex_search=在整行内搜索",
    )
    output_template: str | None = Field(
        default=None,
        description=(
            "仅整理章节时可选，用 $number、$title 重建标题；不填则保留原命中标题"
        ),
    )


class ProfileInput(BaseModel):
    classifiers: list[SectionClassifier] = Field(
        min_length=1,
        description="Agent粗看文本后自行定义的卷、章、番外分类器",
    )
    version: str = Field(default="active", description="active、original、v1 或版本ID")


class NormalizeInput(BaseModel):
    classifiers: list[SectionClassifier] = Field(
        min_length=1,
        description="已通过 get_book_profile 验证过的分类器",
    )
    source_version: str = Field(default="active", description="active、v1 或版本ID")
    blank_lines_before: int = Field(default=1, ge=0, le=3)
    blank_lines_after: int = Field(default=1, ge=0, le=3)


class TextEditOperation(BaseModel):
    operation: EditOperationName = Field(
        description=(
            "replace=替换；delete=删除；insert_before=在命中前插入；"
            "insert_after=在命中后插入"
        ),
    )
    expected_text: str = Field(
        min_length=1,
        description="必须在当前版本中唯一命中的原文，用作安全前置条件",
    )
    new_text: str = Field(
        default="",
        description="替换或插入的新文本；delete 时留空",
    )


class EditInput(BaseModel):
    operations: list[TextEditOperation] = Field(min_length=1)
    source_version: str = Field(default="active", description="active、v1 或版本ID")
    preview: bool = Field(
        default=True,
        description="必须先预览 diff，确认后再以 false 创建新版本",
    )


class DiffInput(BaseModel):
    old_version: str
    new_version: str


class ReadSectionsInput(BaseModel):
    version: str = Field(default="active", description="必须是已经建立章节索引的版本")
    section_type: str = Field(
        default="chapter",
        description="分类器的 name，例如 chapter、volume、extra",
    )
    start_number: int | None = None
    end_number: int | None = None
    numbers: list[int] = Field(default_factory=list)
    mode: SectionReadMode = Field(
        default="full",
        description="head=开头，tail=结尾，head_tail=首尾，full=完整分段",
    )
    per_section_chars: int = Field(default=3000, ge=400, le=20_000)
    max_chars: int = Field(default=40_000, ge=1000, le=80_000)


class SplitSectionsInput(BaseModel):
    version: str = Field(
        default="active",
        description="必须是已通过 normalize_novel_sections 建立索引的版本",
    )
    target_directory: str | None = Field(
        default=None,
        description=(
            "任务工作区内的相对目录，例如 chapters、volumes/volume-1；"
            "工具会自动创建目录。不填时 chapter→chapters、extra→extras、"
            "volume→volumes，自定义单类型→<type>-sections"
        ),
    )
    section_types: list[str] = Field(
        default_factory=list,
        description=(
            "要拆分的分类器名称；默认仅 chapter，也可传 "
            '["chapter", "extra"] 或任意自定义分类名称'
        ),
    )
    start_number: int | None = None
    end_number: int | None = None
    numbers: list[int] = Field(
        default_factory=list,
        description="只拆指定编号；不填则拆分范围内所有匹配分段",
    )
    filename_template: str = Field(
        default="{index:04d}-{type}-{number}-{title}.txt",
        description=(
            "文件名模板，可使用 {index}、{type}、{number}、"
            "{number_raw}、{title}、{heading}；建议保留 {index} 避免重名"
        ),
    )
    metadata_extractors: list[SectionClassifier] = Field(
        default_factory=list,
        description=(
            "当索引缺少 number/title 时，按分段类型从 heading 补提取元数据。"
            "每项 name 对应 section type，pattern 使用 number/title 命名组；"
            "例如 chapter 使用 ^第(?P<number>...)章(?P<title>.*)$。"
            "格式由 Agent 根据实际文件提供，不限于中文章节格式"
        ),
    )
    include_heading: bool = Field(
        default=True,
        description="每个文件是否包含章节标题",
    )
    overwrite: bool = Field(
        default=False,
        description="目标文件已存在时是否明确覆盖",
    )


class CreateResearchDirectoryInput(BaseModel):
    relative_path: str = Field(
        description="任务工作区内的相对目录，例如 notes/characters",
    )
    parents: bool = Field(
        default=True,
        description="是否自动创建缺失的上级目录",
    )


class WriteResearchFileInput(BaseModel):
    relative_path: str = Field(
        description="任务工作区内的相对文件路径，例如 notes/clues.md",
    )
    content: str = Field(
        description="由 Agent 生成并要写入文件的文本内容",
    )
    mode: WorkspaceWriteMode = Field(
        default="create",
        description=(
            "create=仅新建且拒绝覆盖；overwrite=明确覆盖；append=追加"
        ),
    )
    create_parents: bool = Field(
        default=False,
        description="父目录不存在时是否自动创建",
    )


class ListResearchFilesInput(BaseModel):
    relative_path: str = Field(
        default=".",
        description="任务工作区内要列出的相对目录，`.` 表示工作区根目录",
    )
    glob_pattern: str = Field(
        default="*",
        description="文件名 glob，例如 `*.txt`、`*chapter-12-*`",
    )
    recursive: bool = Field(
        default=False,
        description="是否递归搜索子目录",
    )
    include_directories: bool = True
    limit: int = Field(default=500, ge=1, le=5000)


class ReadResearchFilesInput(BaseModel):
    relative_paths: list[str] = Field(
        default_factory=list,
        description="明确要读取的一个或多个工作区相对文件路径",
    )
    glob_pattern: str | None = Field(
        default=None,
        description=(
            "也可使用相对工作区根目录的 glob，例如 `chapters/0001-*.txt`；"
            "复杂的非连续选择请传 relative_paths"
        ),
    )
    start_char: int = Field(default=0, ge=0)
    max_chars_per_file: int = Field(default=20_000, ge=200, le=80_000)
    max_total_chars: int = Field(default=80_000, ge=1000, le=80_000)
    max_files: int = Field(default=50, ge=1, le=5000)


class GrepResearchFilesInput(BaseModel):
    query: str = Field(description="普通文本或正则表达式")
    relative_paths: list[str] = Field(
        default_factory=list,
        description="只搜索指定的一章或多章文件",
    )
    glob_pattern: str | None = Field(
        default=None,
        description=(
            "搜索一组文件，例如 `chapters/*.txt` 或 `chapters/01*.txt`"
        ),
    )
    mode: SearchMode = Field(
        default="literal",
        description="literal=普通文本；regex=Python 正则",
    )
    context_before: int = Field(default=120, ge=0, le=2000)
    context_after: int = Field(default=200, ge=0, le=4000)
    limit: int = Field(default=100, ge=1, le=500)
    max_files: int = Field(default=1000, ge=1, le=5000)
    count_only: bool = False


class SaveArtifactInput(BaseModel):
    artifact_type: str = Field(
        description=(
            "reading_plan/reading_note/stage_summary/book_overview/"
            "structure_report/character_report/technique_card/final_report 等"
        )
    )
    title: str
    content: str
    metadata_text: str = ""


class ListArtifactsInput(BaseModel):
    artifact_type: str | None = None
    keyword: str | None = None
    limit: int = 100


class ReadArtifactsInput(BaseModel):
    artifact_ids: list[str]


class WorkingMemoryInput(BaseModel):
    content: str = Field(description="覆盖式工作记忆，包含已完成事项、关键结论和下一步")


class ProgressInput(BaseModel):
    stage: str
    current: int = 0
    total: int = 0
    unit: str = "步骤"
    detail: str = ""


class CompleteInput(BaseModel):
    summary: str = Field(description="完成说明与覆盖范围")


ContextCitationType = Literal["event", "artifact", "version", "workspace_file"]


class ContextCitation(BaseModel):
    source_type: ContextCitationType = Field(
        description="引用来源：event、artifact、version 或 workspace_file",
    )
    source_id: str = Field(
        min_length=1,
        description=(
            "event 填事件序号或ID；artifact/version 填ID；"
            "workspace_file 填任务工作区相对路径"
        ),
    )
    note: str = Field(
        default="",
        description="该来源支持哪条结论，便于新上下文按需回查",
    )


class CompactResearchContextInput(BaseModel):
    stage: str = Field(description="压缩时的研究阶段")
    completed_work: list[str] = Field(
        default_factory=list,
        description="已经完成且无需重复执行的工作",
    )
    confirmed_findings: list[str] = Field(
        default_factory=list,
        description="已有充分依据的关键结论",
    )
    tentative_findings: list[str] = Field(
        default_factory=list,
        description="仍需验证、不可当作事实使用的暂定结论",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="尚未解决的问题、风险与矛盾",
    )
    operational_lessons: list[str] = Field(
        default_factory=list,
        description="工具使用、文本格式、读取范围等可复用经验",
    )
    next_actions: list[str] = Field(
        min_length=1,
        description="新上下文启动后应按顺序执行的具体动作",
    )
    citations: list[ContextCitation] = Field(
        min_length=1,
        description="关键结论对应的原始事件、产出、版本或工作区文件引用",
    )
    compact_through_sequence: int = Field(
        ge=0,
        description="系统指定的事件水位线；必须原样填写，不能自行提前或延后",
    )


class QueryArchivedEventsInput(BaseModel):
    query: str = Field(
        default="",
        description="可选关键词；为空时按事件序号范围读取",
    )
    epoch_id: str = Field(
        default="",
        description="可选上下文分代ID；为空时使用当前分代的归档范围",
    )
    event_types: list[str] = Field(
        default_factory=list,
        description="可选事件类型过滤，例如 tool_call、tool_result、agent",
    )
    start_sequence: int = Field(default=0, ge=0)
    end_sequence: int = Field(
        default=0,
        ge=0,
        description="0 表示使用所选分代的水位线",
    )
    limit: int = Field(default=30, ge=1, le=200)
    max_chars: int = Field(default=20_000, ge=500, le=80_000)


class ReadContextArchiveInput(BaseModel):
    epoch_id: str = Field(
        default="",
        description="可选上下文分代ID；为空时读取当前分代",
    )
    start_char: int = Field(default=0, ge=0)
    max_chars: int = Field(default=20_000, ge=500, le=80_000)


@dataclass(frozen=True)
class ResearchSnapshot:
    text: str
    instruction_ids: list[str]
    max_event_sequence: int
    active_epoch_id: str | None
    compact_through_sequence: int


@dataclass(frozen=True)
class CompactionContext:
    system_prompt: str
    snapshot: str
    tool_schemas_text: str
    model_name: str
    estimated_input_tokens: int
    compact_through_sequence: int
    source_event_start: int
    previous_epoch_id: str | None


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _next_sequence(db, job_id: str, model) -> int:
    return (
        db.query(func.max(model.sequence))
        .filter(model.job_id == job_id)
        .scalar()
        or 0
    ) + 1


def add_research_event(
    job_id: str,
    event_type: str,
    content: str = "",
    meta: dict | None = None,
) -> ResearchEvent:
    db = _get_db()
    try:
        row = ResearchEvent(
            id=str(uuid.uuid4()),
            job_id=job_id,
            sequence=_next_sequence(db, job_id, ResearchEvent),
            event_type=event_type,
            content=content or "",
            meta_text=_json(meta or {}),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def add_research_instruction(job_id: str, content: str) -> ResearchInstruction:
    db = _get_db()
    try:
        row = ResearchInstruction(
            id=str(uuid.uuid4()),
            job_id=job_id,
            sequence=_next_sequence(db, job_id, ResearchInstruction),
            content=content.strip(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        add_research_event(
            job_id,
            "instruction",
            row.content,
            {"instruction_id": row.id},
        )
        return row
    finally:
        db.close()


def _save_artifact(
    job_id: str,
    artifact_type: str,
    title: str,
    content: str,
    metadata_text: str = "",
) -> dict:
    db = _get_db()
    try:
        row = ResearchArtifact(
            id=str(uuid.uuid4()),
            job_id=job_id,
            artifact_type=artifact_type.strip()[:40],
            title=title.strip()[:500],
            content=content,
            metadata_text=metadata_text,
        )
        db.add(row)
        db.commit()
        add_research_event(
            job_id,
            "artifact",
            f"生成产出：{row.title}",
            {"artifact_id": row.id, "artifact_type": row.artifact_type},
        )
        return {
            "success": True,
            "artifact_id": row.id,
            "artifact_type": row.artifact_type,
            "title": row.title,
        }
    finally:
        db.close()


def _list_artifacts(
    job_id: str,
    artifact_type: str | None = None,
    keyword: str | None = None,
    limit: int = 100,
) -> dict:
    db = _get_db()
    try:
        query = db.query(ResearchArtifact).filter(ResearchArtifact.job_id == job_id)
        if artifact_type:
            query = query.filter(ResearchArtifact.artifact_type == artifact_type)
        if keyword:
            query = query.filter(
                ResearchArtifact.title.ilike(f"%{keyword}%")
                | ResearchArtifact.content.ilike(f"%{keyword}%")
            )
        rows = query.order_by(ResearchArtifact.created_at.desc()).limit(
            max(1, min(int(limit), 300))
        ).all()
        return {
            "count": len(rows),
            "artifacts": [
                {
                    "id": row.id,
                    "artifact_type": row.artifact_type,
                    "title": row.title,
                    "content_preview": row.content[:500],
                    "metadata_text": row.metadata_text[:500],
                }
                for row in rows
            ],
        }
    finally:
        db.close()


def _read_artifacts(job_id: str, artifact_ids: list[str]) -> dict:
    db = _get_db()
    try:
        rows = db.query(ResearchArtifact).filter(
            ResearchArtifact.job_id == job_id,
            ResearchArtifact.id.in_(artifact_ids[:100]),
        ).all()
        return {
            "artifacts": [
                {
                    "id": row.id,
                    "artifact_type": row.artifact_type,
                    "title": row.title,
                    "content": row.content,
                    "metadata_text": row.metadata_text,
                }
                for row in rows
            ]
        }
    finally:
        db.close()


def _update_working_memory(job_id: str, content: str) -> dict:
    db = _get_db()
    try:
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if not job:
            raise ValueError("研究任务不存在")
        job.working_memory = content
        db.commit()
        return {"success": True, "characters": len(content)}
    finally:
        db.close()


def _update_progress(
    job_id: str,
    stage: str,
    current: int = 0,
    total: int = 0,
    unit: str = "步骤",
    detail: str = "",
) -> dict:
    db = _get_db()
    try:
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if not job:
            raise ValueError("研究任务不存在")
        job.stage = stage[:100]
        job.progress_current = max(0, int(current))
        job.progress_total = max(0, int(total))
        job.progress_unit = unit[:30]
        job.progress_detail = detail
        db.commit()
        add_research_event(
            job_id,
            "progress",
            detail or stage,
            {
                "stage": job.stage,
                "current": job.progress_current,
                "total": job.progress_total,
                "unit": job.progress_unit,
            },
        )
        return {"success": True}
    finally:
        db.close()


def _complete_research(job_id: str, summary: str) -> dict:
    db = _get_db()
    try:
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        final_count = db.query(ResearchArtifact).filter(
            ResearchArtifact.job_id == job_id,
            ResearchArtifact.artifact_type == "final_report",
        ).count()
        if not job:
            raise ValueError("研究任务不存在")
        if final_count == 0:
            raise ValueError("完成前必须先保存 final_report")
        job.status = "completed"
        job.completed = True
        job.stage = "分析完成"
        job.progress_detail = summary
        db.commit()
        add_research_event(job_id, "completed", summary)
        return {"success": True, "status": "completed"}
    finally:
        db.close()


def _active_context_epoch(db, job_id: str) -> ResearchContextEpoch | None:
    return db.query(ResearchContextEpoch).filter(
        ResearchContextEpoch.job_id == job_id,
        ResearchContextEpoch.status == "active",
    ).order_by(ResearchContextEpoch.epoch_number.desc()).first()


def _select_context_epoch(
    db,
    job_id: str,
    epoch_id: str = "",
) -> ResearchContextEpoch:
    query = db.query(ResearchContextEpoch).filter(
        ResearchContextEpoch.job_id == job_id,
    )
    row = (
        query.filter(ResearchContextEpoch.id == epoch_id).first()
        if epoch_id
        else query.filter(ResearchContextEpoch.status == "active").order_by(
            ResearchContextEpoch.epoch_number.desc()
        ).first()
    )
    if not row:
        raise ValueError("找不到可查询的上下文分代")
    return row


def _validate_context_citations(
    db,
    job_id: str,
    citations: list[dict],
    watermark: int,
) -> None:
    for citation in citations:
        source_type = citation["source_type"]
        source_id = str(citation["source_id"]).strip()
        if source_type == "event":
            query = db.query(ResearchEvent).filter(
                ResearchEvent.job_id == job_id,
                ResearchEvent.sequence <= watermark,
            )
            row = (
                query.filter(ResearchEvent.sequence == int(source_id)).first()
                if source_id.isdigit()
                else query.filter(ResearchEvent.id == source_id).first()
            )
        elif source_type == "artifact":
            row = db.query(ResearchArtifact).filter(
                ResearchArtifact.job_id == job_id,
                ResearchArtifact.id == source_id,
            ).first()
        elif source_type == "version":
            row = db.query(ResearchTextVersion).filter(
                ResearchTextVersion.job_id == job_id,
                ResearchTextVersion.id == source_id,
            ).first()
        else:
            try:
                _, path = text_tools._resolve_workspace_path(job_id, source_id)
                row = path if path.is_file() else None
            except ValueError:
                row = None
        if not row:
            raise ValueError(
                f"压缩包引用无效或不属于当前任务：{source_type}:{source_id}"
            )


def _commit_context_compaction(
    job_id: str,
    context: CompactionContext,
    **package_fields,
) -> dict:
    watermark = int(package_fields["compact_through_sequence"])
    if watermark != context.compact_through_sequence:
        raise ValueError(
            "事件水位线不一致："
            f"必须填写 {context.compact_through_sequence}，实际为 {watermark}"
        )

    citations = [
        item.model_dump() if isinstance(item, BaseModel) else item
        for item in package_fields["citations"]
    ]
    package_fields = {**package_fields, "citations": citations}
    archive_path: Path | None = None
    db = _get_db()
    try:
        if not db.query(ResearchJob.id).filter(ResearchJob.id == job_id).first():
            raise ValueError("研究任务不存在")
        _validate_context_citations(db, job_id, citations, watermark)

        current = _active_context_epoch(db, job_id)
        if context.previous_epoch_id != (current.id if current else None):
            raise ValueError("上下文分代已变化，请基于最新快照重新压缩")
        epoch_number = (current.epoch_number if current else 0) + 1
        epoch_id = str(uuid.uuid4())
        package = {
            "schema_version": CONTEXT_ARCHIVE_SCHEMA_VERSION,
            "epoch_id": epoch_id,
            "epoch_number": epoch_number,
            **package_fields,
        }
        structured_pack_text = json.dumps(
            package,
            ensure_ascii=False,
            indent=2,
        )
        archive_payload = {
            "schema_version": CONTEXT_ARCHIVE_SCHEMA_VERSION,
            "job_id": job_id,
            "epoch_id": epoch_id,
            "epoch_number": epoch_number,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model_name": context.model_name,
            "source_event_start": context.source_event_start,
            "compact_through_sequence": watermark,
            "estimated_input_tokens": context.estimated_input_tokens,
            "rendered_request": {
                "system_prompt": context.system_prompt,
                "snapshot": context.snapshot,
                "tool_schemas": json.loads(context.tool_schemas_text),
            },
        }
        archive_bytes = gzip.compress(
            json.dumps(
                archive_payload,
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
            mtime=0,
        )
        archive_dir = text_tools._job_dir(job_id) / "context"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / f"epoch-{epoch_number:04d}-{epoch_id}.json.gz"
        temporary = archive_path.with_name(f".{archive_path.name}.{uuid.uuid4()}.tmp")
        temporary.write_bytes(archive_bytes)
        os.replace(temporary, archive_path)

        if current:
            current.status = "superseded"
        row = ResearchContextEpoch(
            id=epoch_id,
            job_id=job_id,
            epoch_number=epoch_number,
            status="active",
            source_event_start=context.source_event_start,
            compact_through_sequence=watermark,
            archive_path=str(archive_path),
            archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
            structured_pack_text=structured_pack_text,
            rendered_context_chars=len(context.system_prompt) + len(context.snapshot),
            estimated_input_tokens=context.estimated_input_tokens,
            model_name=context.model_name,
            schema_version=CONTEXT_ARCHIVE_SCHEMA_VERSION,
        )
        db.add(row)
        db.commit()
        return {
            "success": True,
            "epoch_id": epoch_id,
            "epoch_number": epoch_number,
            "compact_through_sequence": watermark,
            "archive_sha256": row.archive_sha256,
            "next_step": "当前上下文已封存；系统将使用压缩包启动新的上下文分代",
        }
    except Exception:
        db.rollback()
        if archive_path and archive_path.exists():
            archive_path.unlink()
        raise
    finally:
        db.close()


def _query_archived_events(
    job_id: str,
    query: str = "",
    epoch_id: str = "",
    event_types: list[str] | None = None,
    start_sequence: int = 0,
    end_sequence: int = 0,
    limit: int = 30,
    max_chars: int = 20_000,
) -> dict:
    db = _get_db()
    try:
        epoch = _select_context_epoch(db, job_id, epoch_id)
        # 当前压缩包可能沿用并引用更早分代的结论，因此默认允许回查该任务
        # 从第一条事件到所选水位线的全部不可变事件。
        lower = max(1, int(start_sequence or 0))
        upper = min(
            epoch.compact_through_sequence,
            int(end_sequence or epoch.compact_through_sequence),
        )
        rows_query = db.query(ResearchEvent).filter(
            ResearchEvent.job_id == job_id,
            ResearchEvent.sequence >= lower,
            ResearchEvent.sequence <= upper,
        )
        if event_types:
            rows_query = rows_query.filter(
                ResearchEvent.event_type.in_(event_types[:30])
            )
        rows = rows_query.order_by(ResearchEvent.sequence).all()
        needle = query.casefold().strip()
        if needle:
            rows = [
                row for row in rows
                if needle in row.content.casefold() or needle in row.meta_text.casefold()
            ]
        selected = []
        remaining = max_chars
        for row in rows[: max(1, min(limit, 200))]:
            content = row.content[:remaining]
            if not content:
                break
            selected.append({
                "id": row.id,
                "sequence": row.sequence,
                "event_type": row.event_type,
                "content": content,
                "meta_text": row.meta_text[:2000],
            })
            remaining -= len(content)
            if remaining <= 0:
                break
        return {
            "epoch_id": epoch.id,
            "range": [lower, upper],
            "count": len(selected),
            "events": selected,
            "truncated": len(selected) < len(rows),
        }
    finally:
        db.close()


def _read_context_archive(
    job_id: str,
    epoch_id: str = "",
    start_char: int = 0,
    max_chars: int = 20_000,
) -> dict:
    db = _get_db()
    try:
        epoch = _select_context_epoch(db, job_id, epoch_id)
        path = Path(epoch.archive_path)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != epoch.archive_sha256:
            raise ValueError("上下文归档校验失败，文件可能已被修改")
        text = gzip.decompress(data).decode("utf-8")
        start = min(int(start_char), len(text))
        end = min(len(text), start + int(max_chars))
        return {
            "epoch_id": epoch.id,
            "start_char": start,
            "end_char": end,
            "total_chars": len(text),
            "content": text[start:end],
            "has_more": end < len(text),
        }
    finally:
        db.close()


def _wrap_text_tool(
    job_id: str,
    name: str,
    description: str,
    args_schema: type[BaseModel],
    func: Callable,
) -> StructuredTool:
    def call(**kwargs):
        # StructuredTool/Pydantic 的不同版本可能把嵌套模型保留为
        # BaseModel；确定性文本工具只接收普通 Python 数据结构。
        kwargs = {
            key: value.model_dump() if isinstance(value, BaseModel) else [
                item.model_dump() if isinstance(item, BaseModel) else item
                for item in value
            ] if isinstance(value, list) else value
            for key, value in kwargs.items()
        }
        return _json(func(job_id=job_id, **kwargs))

    return StructuredTool.from_function(
        func=call,
        name=name,
        description=description,
        args_schema=args_schema,
    )


def build_research_tools(job_id: str) -> list[StructuredTool]:
    return [
        _wrap_text_tool(
            job_id, "inspect_novel_text",
            "确定性采样查看原始或整理文本；用于先粗看编码和格式，不做任何修改。",
            InspectInput, text_tools.inspect_novel_text,
        ),
        _wrap_text_tool(
            job_id, "grep_novel_text",
            "在指定文本版本中做普通或正则搜索，返回命中位置和上下文。",
            GrepInput, text_tools.grep_novel_text,
        ),
        _wrap_text_tool(
            job_id, "create_cleaned_copy",
            "从原始版本创建UTF-8整理副本，只做Agent明确指定的编码与换行处理。",
            CreateCopyInput, text_tools.create_cleaned_copy,
        ),
        _wrap_text_tool(
            job_id, "transform_novel_text",
            (
                "按Agent输入的噪点/替换规则批量转换文本。operation 只允许 "
                "delete_line、literal_replace、regex_replace、delete_between；"
                "必须先 preview=true，再正式执行。"
            ),
            TransformInput, text_tools.transform_novel_text,
        ),
        _wrap_text_tool(
            job_id, "get_book_profile",
            (
                "按Agent输入的卷、章、番外正则分类器统计结构、缺号、重复和异常长度。"
                "分类器必须提供 name、pattern、mode；正则可提供 number/title 命名组。"
            ),
            ProfileInput, text_tools.get_book_profile,
        ),
        _wrap_text_tool(
            job_id, "normalize_novel_sections",
            "按Agent确认的分类器整理标题换行、生成新文本版本和分段索引。",
            NormalizeInput, text_tools.normalize_novel_sections,
        ),
        _wrap_text_tool(
            job_id, "split_novel_sections_to_files",
            (
                "把已索引版本中的章、卷、番外或自定义分段拆成任务工作区内的"
                "独立 UTF-8 文件，同时生成 manifest.tsv。支持按类型、编号范围、"
                "编号列表和文件名模板选择；索引元数据缺失时可用 Agent 提供的"
                "metadata_extractors 从标题补提取，默认拆分全部 chapter。"
            ),
            SplitSectionsInput, text_tools.split_novel_sections_to_files,
        ),
        _wrap_text_tool(
            job_id, "edit_novel_text",
            "使用带expected_text前置条件的补丁编辑整理文本；原始文本不可编辑。",
            EditInput, text_tools.edit_novel_text,
        ),
        _wrap_text_tool(
            job_id, "diff_novel_versions",
            "确定性比较两个文本版本，检查清理或编辑是否误伤正文。",
            DiffInput, text_tools.diff_novel_versions,
        ),
        _wrap_text_tool(
            job_id, "read_novel_sections",
            "按已建立的索引读取指定卷、章或番外原文；不做总结。",
            ReadSectionsInput, text_tools.read_novel_sections,
        ),
        _wrap_text_tool(
            job_id, "create_research_directory",
            (
                "在当前研究任务的隔离工作区创建任意相对目录；"
                "不能访问或修改 original、cleaned、indexes。"
            ),
            CreateResearchDirectoryInput, text_tools.create_research_directory,
        ),
        _wrap_text_tool(
            job_id, "write_research_file",
            (
                "在隔离工作区新建、覆盖或追加 UTF-8 文本文件。"
                "适合保存 Agent 自定义的清单、线索表和中间资料。"
            ),
            WriteResearchFileInput, text_tools.write_research_file,
        ),
        _wrap_text_tool(
            job_id, "list_research_files",
            (
                "按目录和 glob 列出任务工作区文件，"
                "用于发现分章文件、manifest 和 Agent 自建资料。"
            ),
            ListResearchFilesInput, text_tools.list_research_files,
        ),
        _wrap_text_tool(
            job_id, "read_research_files",
            (
                "读取任务工作区中的一个、多个或 glob 匹配的 UTF-8 文件；"
                "可精确选择某一章或若干章，并受总字符预算限制。"
            ),
            ReadResearchFilesInput, text_tools.read_research_files,
        ),
        _wrap_text_tool(
            job_id, "grep_research_files",
            (
                "在任务工作区的指定文件或 glob 文件集合中做普通/正则检索，"
                "返回文件路径、行号和上下文。可只查某几章，也可跨全部分章。"
            ),
            GrepResearchFilesInput, text_tools.grep_research_files,
        ),
        _wrap_text_tool(
            job_id, "save_research_artifact",
            "保存由你亲自生成的阅读笔记、阶段报告、技法卡或最终报告。",
            SaveArtifactInput, _save_artifact,
        ),
        _wrap_text_tool(
            job_id, "list_research_artifacts",
            "按类型或关键词列出已保存研究产出，方便恢复长期任务。",
            ListArtifactsInput, _list_artifacts,
        ),
        _wrap_text_tool(
            job_id, "read_research_artifacts",
            "读取指定研究产出的完整内容。",
            ReadArtifactsInput, _read_artifacts,
        ),
        _wrap_text_tool(
            job_id, "update_working_memory",
            "覆盖更新长期工作记忆；内容由你生成，工具只保存。",
            WorkingMemoryInput, _update_working_memory,
        ),
        _wrap_text_tool(
            job_id, "update_research_progress",
            "更新用户可见的阶段、章节进度和当前工作说明。",
            ProgressInput, _update_progress,
        ),
        _wrap_text_tool(
            job_id, "query_archived_research_events",
            (
                "按关键词、事件类型或序号范围查询已经压缩归档的原始研究事件。"
                "当结构化压缩包缺少细节或需要核对原始工具结果时使用。"
            ),
            QueryArchivedEventsInput, _query_archived_events,
        ),
        _wrap_text_tool(
            job_id, "read_research_context_archive",
            (
                "分页读取某次上下文分代落盘的完整原始请求，包含系统提示词、"
                "当时快照和工具定义；仅在事件查询无法还原细节时使用。"
            ),
            ReadContextArchiveInput, _read_context_archive,
        ),
        _wrap_text_tool(
            job_id, "complete_research",
            "全书分析真正完成后结束后台循环；调用前必须已经保存final_report。",
            CompleteInput, _complete_research,
        ),
    ]


def build_context_compaction_tool(
    job_id: str,
    context: CompactionContext,
) -> StructuredTool:
    return _wrap_text_tool(
        job_id,
        "compact_research_context",
        (
            "强制上下文换代工具。把当前完整研究状态总结为结构化压缩包，"
            "同时由工具将本轮完整原始请求不可变归档到磁盘。"
            "compact_through_sequence 必须使用系统指定水位线。"
        ),
        CompactResearchContextInput,
        lambda job_id, **kwargs: _commit_context_compaction(
            job_id,
            context,
            **kwargs,
        ),
    )


def _compaction_tool_schemas_text() -> str:
    return json.dumps(
        [{
            "name": "compact_research_context",
            "description": (
                "强制上下文换代工具。把当前完整研究状态总结为结构化压缩包，"
                "同时由工具将本轮完整原始请求不可变归档到磁盘。"
                "compact_through_sequence 必须使用系统指定水位线。"
            ),
            "parameters": CompactResearchContextInput.model_json_schema(),
        }],
        ensure_ascii=False,
        sort_keys=True,
    )


def _build_job_snapshot(
    job_id: str,
    recent_context_char_limit: int = RECENT_CONTEXT_CHAR_LIMIT,
) -> ResearchSnapshot:
    db = _get_db()
    try:
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if not job:
            raise ValueError("研究任务不存在")
        active = db.query(ResearchTextVersion).filter(
            ResearchTextVersion.id == job.active_version_id
        ).first()
        artifacts = db.query(ResearchArtifact).filter(
            ResearchArtifact.job_id == job_id
        ).order_by(ResearchArtifact.created_at.desc()).limit(250).all()
        instructions = db.query(ResearchInstruction).filter(
            ResearchInstruction.job_id == job_id,
            ResearchInstruction.consumed.is_(False),
        ).order_by(ResearchInstruction.sequence).all()
        epoch = _active_context_epoch(db, job_id)
        watermark = epoch.compact_through_sequence if epoch else 0
        events = db.query(ResearchEvent).filter(
            ResearchEvent.job_id == job_id,
            ResearchEvent.sequence > watermark,
        ).order_by(ResearchEvent.sequence.desc()).all()
        max_event_sequence = (
            db.query(func.max(ResearchEvent.sequence))
            .filter(ResearchEvent.job_id == job_id)
            .scalar()
            or 0
        )

        artifact_index = "\n".join(
            f"- {row.id} | {row.artifact_type} | {row.title}"
            for row in reversed(artifacts)
        ) or "（尚无）"
        event_parts = []
        budget = max(10_000, int(recent_context_char_limit))
        for event in events:
            shown = event.content
            if len(shown) > 50_000:
                shown = shown[:50_000] + "\n…（事件内容已截断）"
            part = f"[event:{event.sequence}][{event.event_type}] {shown}"
            if len(part) > budget:
                continue
            event_parts.append(part)
            budget -= len(part)
        recent = "\n\n".join(reversed(event_parts)) or "（尚无）"
        pending = "\n".join(f"- {row.content}" for row in instructions) or "（无）"

        context_section = (
            "## 当前上下文分代\n"
            f"- epoch_id: {epoch.id}\n"
            f"- epoch_number: {epoch.epoch_number}\n"
            f"- 事件水位线: {epoch.compact_through_sequence}\n\n"
            "### 结构化压缩包\n"
            f"{epoch.structured_pack_text}\n\n"
            "旧事件和完整原始请求未丢失；缺少细节时使用 "
            "query_archived_research_events 或 read_research_context_archive 回查。"
            if epoch
            else (
                "## 长期工作记忆\n"
                f"{job.working_memory or '（尚未建立；请尽快在完成初步格式检查后更新）'}"
            )
        )
        snapshot = f"""
## 当前研究任务
- job_id: {job.id}
- 文件: {job.original_filename}
- 状态: {job.status}
- 阶段: {job.stage}
- 当前文本版本: {f"v{active.version_number} / {active.id}" if active else "无"}
- 进度: {job.progress_current}/{job.progress_total} {job.progress_unit}
- 进度说明: {job.progress_detail or "无"}

## 用户尚未处理的新要求
{pending}

{context_section}

## 已保存产出索引
{artifact_index}

## 当前分代执行记录（水位线之后）
{recent}

请决定并执行下一步。只要全书分析尚未真正完成，就继续调用工具推进。
""".strip()
        return ResearchSnapshot(
            text=snapshot,
            instruction_ids=[row.id for row in instructions],
            max_event_sequence=max_event_sequence,
            active_epoch_id=epoch.id if epoch else None,
            compact_through_sequence=watermark,
        )
    finally:
        db.close()


def _job_snapshot(job_id: str) -> tuple[str, list[str]]:
    """保留原有测试/调用接口；运行循环使用包含水位线元数据的版本。"""
    snapshot = _build_job_snapshot(job_id)
    return snapshot.text, snapshot.instruction_ids


def _mark_instructions_consumed(ids: list[str]) -> None:
    if not ids:
        return
    db = _get_db()
    try:
        db.query(ResearchInstruction).filter(
            ResearchInstruction.id.in_(ids)
        ).update({"consumed": True}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _job_model_pref(job_id: str) -> dict:
    db = _get_db()
    try:
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        user = db.query(User).filter(User.id == job.user_id).first() if job else None
        return {
            "primary": user.primary_model if user else None,
            "fallback": user.fallback_model if user else None,
        }
    finally:
        db.close()


def _tool_schemas_text(tools: list[StructuredTool]) -> str:
    schemas = []
    for tool in tools:
        args_schema = getattr(tool, "args_schema", None)
        if args_schema and hasattr(args_schema, "model_json_schema"):
            parameters = args_schema.model_json_schema()
        elif args_schema and hasattr(args_schema, "schema"):
            parameters = args_schema.schema()
        else:
            parameters = {}
        schemas.append({
            "name": tool.name,
            "description": tool.description,
            "parameters": parameters,
        })
    return json.dumps(schemas, ensure_ascii=False, sort_keys=True)


def _research_context_limit(pref: dict) -> int:
    limits = []
    for model_name in (
        pref.get("primary") or settings.default_model,
        pref.get("fallback") if pref.get("fallback") is not None else settings.fallback_model,
    ):
        if not model_name:
            continue
        try:
            limit = settings.get_model_context_window(model_name)
        except (KeyError, ValueError):
            limit = None
        if limit:
            limits.append(limit)
    return min(limits) if limits else DEFAULT_RESEARCH_CONTEXT_WINDOW


def _estimate_context_tokens(
    system_prompt: str,
    snapshot: str,
    tool_schemas_text: str,
) -> int:
    chars = len(system_prompt) + len(snapshot) + len(tool_schemas_text)
    return max(1, (chars + CHARS_PER_ESTIMATED_TOKEN - 1) // CHARS_PER_ESTIMATED_TOKEN)


def _context_requires_compaction(
    estimated_input_tokens: int,
    context_limit: int,
) -> bool:
    projected = estimated_input_tokens + COMPACTION_OUTPUT_RESERVE_TOKENS
    return projected >= int(context_limit * CONTEXT_COMPACTION_THRESHOLD)


def _snapshot_event_budget(
    context_limit: int,
    system_prompt: str,
    tool_schemas_text: str,
) -> int:
    """让快照略微越过触发线但仍留在模型上限内。

    这也保护升级前已经积累大量事件的任务：首次运行新代码时不会先构造一个
    远超模型上限的请求，而是携带最近的可容纳事件并立即进入压缩流程。
    """
    target_input_tokens = (
        int(context_limit * (CONTEXT_COMPACTION_THRESHOLD + 0.02))
        - COMPACTION_OUTPUT_RESERVE_TOKENS
    )
    target_chars = target_input_tokens * CHARS_PER_ESTIMATED_TOKEN
    fixed_chars = len(system_prompt) + len(tool_schemas_text) + 40_000
    return min(
        RECENT_CONTEXT_CHAR_LIMIT,
        max(70_000, target_chars - fixed_chars),
    )


def _set_job_status(job_id: str, status: str, stage: str | None = None, error: str = ""):
    db = _get_db()
    try:
        job = db.query(ResearchJob).filter(ResearchJob.id == job_id).first()
        if not job:
            return
        job.status = status
        if stage:
            job.stage = stage
        job.error = error
        db.commit()
    finally:
        db.close()


def _get_job_status(job_id: str) -> str | None:
    db = _get_db()
    try:
        row = db.query(ResearchJob.status).filter(ResearchJob.id == job_id).first()
        return row[0] if row else None
    finally:
        db.close()


class ResearchAgentManager:
    """进程内后台任务管理器；状态与每一步结果均持久化到数据库。"""

    def __init__(self):
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self, job_id: str) -> None:
        existing = self._tasks.get(job_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self._run(job_id), name=f"research-{job_id}")
        self._tasks[job_id] = task

        def cleanup(done_task):
            if self._tasks.get(job_id) is done_task:
                self._tasks.pop(job_id, None)

        task.add_done_callback(cleanup)

    async def pause(self, job_id: str) -> None:
        _set_job_status(job_id, "paused", "已暂停")
        add_research_event(job_id, "paused", "用户中断了研究任务")
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def recover_running(self) -> None:
        db = _get_db()
        try:
            ids = [
                row[0]
                for row in db.query(ResearchJob.id).filter(
                    ResearchJob.status.in_(["queued", "running"])
                ).all()
            ]
        finally:
            db.close()
        for job_id in ids:
            self.start(job_id)

    async def _run(self, job_id: str) -> None:
        _set_job_status(job_id, "running", "Agent正在检查文件")
        add_research_event(job_id, "started", "独立研究 Agent 已开始工作")
        tools = build_research_tools(job_id)
        tools_by_name = {tool.name: tool for tool in tools}
        pref = _job_model_pref(job_id)
        system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
        normal_tool_schemas = _tool_schemas_text(tools)
        context_limit = _research_context_limit(pref)
        snapshot_event_budget = _snapshot_event_budget(
            context_limit,
            system_prompt,
            normal_tool_schemas,
        )
        effective_model = pref.get("primary") or settings.default_model
        retry_delay = 3

        def create_llm_pair():
            llm = get_llm(
                temperature=0.2,
                streaming=False,
                primary=pref.get("primary"),
                fallback=pref.get("fallback"),
            )
            return llm, bind_tools_to_llm(llm, tools)

        llm, llm_with_tools = create_llm_pair()

        try:
            while _get_job_status(job_id) == "running":
                snapshot_state = _build_job_snapshot(
                    job_id,
                    recent_context_char_limit=snapshot_event_budget,
                )
                snapshot = snapshot_state.text
                instruction_ids = snapshot_state.instruction_ids
                estimated_tokens = _estimate_context_tokens(
                    system_prompt,
                    snapshot,
                    normal_tool_schemas,
                )
                if _context_requires_compaction(estimated_tokens, context_limit):
                    watermark = snapshot_state.max_event_sequence
                    compaction_prompt = (
                        f"{snapshot}\n\n"
                        "## 系统强制上下文换代\n"
                        f"预计本轮输入 {estimated_tokens} tokens，上下文上限 "
                        f"{context_limit} tokens，已达到 "
                        f"{CONTEXT_COMPACTION_THRESHOLD:.0%} 门槛。\n"
                        "你现在只能调用 compact_research_context。请完整保留研究进度、"
                        "已确认与待验证结论、关键工具经验和下一步动作；关键结论必须"
                        "提供可回查引用。\n"
                        f"compact_through_sequence 必须填写 {watermark}。"
                    )
                    compaction_schemas = _compaction_tool_schemas_text()
                    compaction_context = CompactionContext(
                        system_prompt=system_prompt,
                        snapshot=compaction_prompt,
                        tool_schemas_text=compaction_schemas,
                        model_name=effective_model,
                        estimated_input_tokens=_estimate_context_tokens(
                            system_prompt,
                            compaction_prompt,
                            compaction_schemas,
                        ),
                        compact_through_sequence=watermark,
                        source_event_start=snapshot_state.compact_through_sequence + 1,
                        previous_epoch_id=snapshot_state.active_epoch_id,
                    )
                    compaction_tool = build_context_compaction_tool(
                        job_id,
                        compaction_context,
                    )
                    forced_llm = llm.bind_tools(
                        [compaction_tool],
                        tool_choice=compaction_tool.name,
                    )
                    add_research_event(
                        job_id,
                        "compaction_required",
                        (
                            f"上下文预计使用 {estimated_tokens}/{context_limit} tokens，"
                            f"强制压缩至事件水位线 {watermark}"
                        ),
                    )
                    try:
                        response = await forced_llm.ainvoke([
                            SystemMessage(content=system_prompt),
                            HumanMessage(content=compaction_prompt),
                        ])
                        calls = extract_tool_calls(response)
                        if not calls and getattr(response, "tool_calls", None):
                            calls = list(response.tool_calls)
                        calls = [
                            call for call in calls
                            if call.get("name") == compaction_tool.name
                        ]
                        if len(calls) != 1:
                            raise ValueError("模型未按要求调用唯一的上下文压缩工具")
                        args = calls[0].get("args") or {}
                        add_research_event(
                            job_id,
                            "tool_call",
                            "调用 compact_research_context",
                            {"tool": compaction_tool.name, "args": args},
                        )
                        result = await compaction_tool.ainvoke(args)
                        parsed_result = json.loads(str(result))
                        add_research_event(
                            job_id,
                            "tool_result",
                            str(result),
                            {"tool": compaction_tool.name},
                        )
                        if not parsed_result.get("success"):
                            raise ValueError(
                                parsed_result.get("error") or "上下文压缩未成功"
                            )
                        _mark_instructions_consumed(instruction_ids)
                        add_research_event(
                            job_id,
                            "context_compacted",
                            (
                                f"已切换到上下文分代 {parsed_result['epoch_number']}，"
                                f"水位线 {parsed_result['compact_through_sequence']}"
                            ),
                            {"epoch_id": parsed_result["epoch_id"]},
                        )
                        # 新建模型绑定，明确切断旧一代调用对象及其任何供应商侧状态。
                        llm, llm_with_tools = create_llm_pair()
                        retry_delay = 3
                        await asyncio.sleep(0)
                        continue
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.exception(
                            "research context compaction failed job_id=%s",
                            job_id,
                        )
                        add_research_event(
                            job_id,
                            "retry",
                            f"上下文压缩失败，将基于最新水位线重试：{exc}",
                        )
                        await asyncio.sleep(retry_delay)
                        retry_delay = min(60, retry_delay * 2)
                        continue

                try:
                    response = await llm_with_tools.ainvoke([
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=snapshot),
                    ])
                    retry_delay = 3
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("research llm call failed job_id=%s", job_id)
                    add_research_event(
                        job_id,
                        "retry",
                        f"模型调用失败，将自动重试：{exc}",
                    )
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(60, retry_delay * 2)
                    continue

                _mark_instructions_consumed(instruction_ids)
                content = extract_text_content(getattr(response, "content", ""))
                if content:
                    add_research_event(job_id, "agent", content)
                calls = extract_tool_calls(response)
                if not calls and getattr(response, "tool_calls", None):
                    calls = list(response.tool_calls)
                if not calls:
                    add_research_event(
                        job_id,
                        "continue",
                        "Agent尚未调用工具，系统将继续要求其推进任务。",
                    )
                    await asyncio.sleep(0)
                    continue

                for call in calls:
                    if _get_job_status(job_id) != "running":
                        break
                    name = call.get("name") or ""
                    args = call.get("args") or {}
                    add_research_event(
                        job_id,
                        "tool_call",
                        f"调用 {name}",
                        {"tool": name, "args": args},
                    )
                    tool = tools_by_name.get(name)
                    if not tool:
                        result = _json({"success": False, "error": f"未知工具 {name}"})
                    else:
                        try:
                            result = await tool.ainvoke(args)
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            result = _json({
                                "success": False,
                                "error": str(exc),
                                "tool": name,
                            })
                    add_research_event(
                        job_id,
                        "tool_result",
                        str(result),
                        {"tool": name},
                    )
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            if _get_job_status(job_id) == "running":
                _set_job_status(job_id, "paused", "任务已中断")
            raise
        except Exception as exc:
            logger.exception("research agent crashed job_id=%s", job_id)
            _set_job_status(job_id, "error", "运行错误", str(exc))
            add_research_event(job_id, "error", str(exc))


research_agent_manager = ResearchAgentManager()
