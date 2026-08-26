"""写作 Agent 读取小说研究 Agent 产出的只读工具。"""
import asyncio
import json
from functools import partial
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import or_

from models.research import ResearchArtifact, ResearchJob


def _get_db():
    from database import SessionLocal
    return SessionLocal()


def _get_current_user_id() -> str | None:
    try:
        from services.agents.supervisor import get_context
        return get_context().get("user_id")
    except Exception:
        return None


class ListResearchArtifactsInput(BaseModel):
    job_id: Optional[str] = Field(
        default=None,
        description="研究任务 ID；省略时查询当前用户的全部研究成果。",
    )
    artifact_type: Optional[str] = Field(
        default=None,
        description="成果类型过滤，例如 final_report 或 technique_card。",
    )
    keyword: Optional[str] = Field(
        default=None,
        description="在原小说文件名、成果标题和成果正文中搜索的关键词。",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="最多返回多少条成果，范围 1-100。",
    )
    reason: Optional[str] = Field(
        default=None,
        description="调用此工具的原因，仅用于执行记录。",
    )


class ReadResearchArtifactsInput(BaseModel):
    artifact_ids: list[str] = Field(
        min_length=1,
        max_length=20,
        description=(
            "要读取的研究成果 ID 列表，必须来自 list_research_artifacts。"
            "一次最多读取 20 条。"
        ),
    )
    reason: Optional[str] = Field(
        default=None,
        description="调用此工具的原因，仅用于执行记录。",
    )


def _list_research_artifacts_sync(
    job_id: str | None = None,
    artifact_type: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
    reason: str | None = None,
) -> str:
    user_id = _get_current_user_id()
    if not user_id:
        return json.dumps({
            "success": False,
            "error": "当前写作会话缺少 user_id，无法读取研究成果。",
            "artifacts": [],
            "total": 0,
        }, ensure_ascii=False)

    db = _get_db()
    try:
        query = (
            db.query(ResearchArtifact, ResearchJob)
            .join(ResearchJob, ResearchArtifact.job_id == ResearchJob.id)
            .filter(ResearchJob.user_id == user_id)
        )
        if job_id:
            query = query.filter(ResearchJob.id == job_id)
        if artifact_type:
            query = query.filter(
                ResearchArtifact.artifact_type == artifact_type.strip()
            )
        if keyword and keyword.strip():
            pattern = f"%{keyword.strip()}%"
            query = query.filter(or_(
                ResearchJob.original_filename.ilike(pattern),
                ResearchArtifact.title.ilike(pattern),
                ResearchArtifact.content.ilike(pattern),
            ))

        rows = (
            query.order_by(ResearchArtifact.created_at.desc())
            .limit(max(1, min(int(limit), 100)))
            .all()
        )
        artifacts = [
            {
                "id": artifact.id,
                "job_id": job.id,
                "source_filename": job.original_filename,
                "job_status": job.status,
                "progress": {
                    "current": job.progress_current,
                    "total": job.progress_total,
                    "unit": job.progress_unit,
                    "detail": job.progress_detail,
                },
                "artifact_type": artifact.artifact_type,
                "title": artifact.title,
                "content_preview": (artifact.content or "")[:500],
                "created_at": (
                    artifact.created_at.isoformat()
                    if artifact.created_at else None
                ),
            }
            for artifact, job in rows
        ]
        return json.dumps({
            "success": True,
            "artifacts": artifacts,
            "total": len(artifacts),
        }, ensure_ascii=False)
    finally:
        db.close()


def _read_research_artifacts_sync(
    artifact_ids: list[str],
    reason: str | None = None,
) -> str:
    user_id = _get_current_user_id()
    if not user_id:
        return json.dumps({
            "success": False,
            "error": "当前写作会话缺少 user_id，无法读取研究成果。",
            "artifacts": [],
        }, ensure_ascii=False)

    requested_ids = list(dict.fromkeys(artifact_ids))[:20]
    db = _get_db()
    try:
        rows = (
            db.query(ResearchArtifact, ResearchJob)
            .join(ResearchJob, ResearchArtifact.job_id == ResearchJob.id)
            .filter(
                ResearchJob.user_id == user_id,
                ResearchArtifact.id.in_(requested_ids),
            )
            .all()
        )
        rows_by_id = {
            artifact.id: (artifact, job)
            for artifact, job in rows
        }
        artifacts = []
        for artifact_id in requested_ids:
            row = rows_by_id.get(artifact_id)
            if not row:
                continue
            artifact, job = row
            artifacts.append({
                "id": artifact.id,
                "job_id": job.id,
                "source_filename": job.original_filename,
                "job_status": job.status,
                "progress": {
                    "current": job.progress_current,
                    "total": job.progress_total,
                    "unit": job.progress_unit,
                    "detail": job.progress_detail,
                },
                "artifact_type": artifact.artifact_type,
                "title": artifact.title,
                "content": artifact.content,
                "metadata_text": artifact.metadata_text,
                "created_at": (
                    artifact.created_at.isoformat()
                    if artifact.created_at else None
                ),
            })

        found_ids = {item["id"] for item in artifacts}
        return json.dumps({
            "success": True,
            "artifacts": artifacts,
            "total": len(artifacts),
            "unavailable_artifact_ids": [
                artifact_id
                for artifact_id in requested_ids
                if artifact_id not in found_ids
            ],
        }, ensure_ascii=False)
    finally:
        db.close()


async def _list_research_artifacts_async(
    job_id=None,
    artifact_type=None,
    keyword=None,
    limit=50,
    reason=None,
) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(
            _list_research_artifacts_sync,
            job_id,
            artifact_type,
            keyword,
            limit,
            reason,
        ),
    )


async def _read_research_artifacts_async(
    artifact_ids,
    reason=None,
) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        partial(_read_research_artifacts_sync, artifact_ids, reason),
    )


list_research_artifacts = StructuredTool.from_function(
    coroutine=_list_research_artifacts_async,
    func=_list_research_artifacts_sync,
    name="list_research_artifacts",
    description=(
        "列出当前用户由小说研究 Agent 生成的研究报告和技法卡。"
        "写作前先用此工具寻找 final_report 或与当前场景相关的 technique_card，"
        "再把返回的真实成果 ID 交给 read_research_artifacts。"
    ),
    args_schema=ListResearchArtifactsInput,
)


read_research_artifacts = StructuredTool.from_function(
    coroutine=_read_research_artifacts_async,
    func=_read_research_artifacts_sync,
    name="read_research_artifacts",
    description=(
        "按成果 ID 读取当前用户的完整小说研究报告或技法卡。"
        "研究内容只用于借鉴写作方法，不代表当前作品的角色、设定或剧情事实。"
    ),
    args_schema=ReadResearchArtifactsInput,
)


research_tools = [
    list_research_artifacts,
    read_research_artifacts,
]
