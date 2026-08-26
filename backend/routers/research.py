"""独立小说研究 Agent API。"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models.research import (
    ResearchArtifact,
    ResearchContextEpoch,
    ResearchEvent,
    ResearchJob,
    ResearchTextVersion,
)
from models.user import User
from routers.auth import get_current_user
from services.research_agent import (
    add_research_instruction,
    research_agent_manager,
)
from services.research_text_tools import create_job_files


router = APIRouter(prefix="/research", tags=["research"])
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


class ContinueRequest(BaseModel):
    message: str


def _serialize_job(job: ResearchJob) -> dict:
    return {
        "id": job.id,
        "original_filename": job.original_filename,
        "status": job.status,
        "stage": job.stage,
        "active_version_id": job.active_version_id,
        "working_memory": job.working_memory,
        "progress_current": job.progress_current,
        "progress_total": job.progress_total,
        "progress_unit": job.progress_unit,
        "progress_detail": job.progress_detail,
        "error": job.error,
        "completed": job.completed,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _owned_job(db: Session, job_id: str, user_id: str) -> ResearchJob:
    job = db.query(ResearchJob).filter(
        ResearchJob.id == job_id,
        ResearchJob.user_id == user_id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    return job


@router.post("/jobs")
async def upload_and_start(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=500),
    user: User = Depends(get_current_user),
):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件不能超过100MB")
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件不能超过100MB")
    if not filename.lower().endswith(".txt"):
        raise HTTPException(status_code=400, detail="第一版仅支持TXT文件")
    try:
        created = create_job_files(user.id, filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    research_agent_manager.start(created["job_id"])
    return created


@router.get("/jobs")
def list_jobs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.query(ResearchJob).filter(
        ResearchJob.user_id == user.id
    ).order_by(ResearchJob.created_at.desc()).all()
    return {"jobs": [_serialize_job(row) for row in rows]}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = _owned_job(db, job_id, user.id)
    versions = db.query(ResearchTextVersion).filter(
        ResearchTextVersion.job_id == job_id
    ).order_by(ResearchTextVersion.version_number).all()
    artifacts = db.query(ResearchArtifact).filter(
        ResearchArtifact.job_id == job_id
    ).order_by(ResearchArtifact.created_at.desc()).all()
    epochs = db.query(ResearchContextEpoch).filter(
        ResearchContextEpoch.job_id == job_id
    ).order_by(ResearchContextEpoch.epoch_number).all()
    result = _serialize_job(job)
    result["versions"] = [
        {
            "id": row.id,
            "version_number": row.version_number,
            "kind": row.kind,
            "encoding": row.encoding,
            "sha256": row.sha256,
            "has_index": bool(row.index_path),
            "manifest_text": row.manifest_text,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in versions
    ]
    result["artifacts"] = [
        {
            "id": row.id,
            "artifact_type": row.artifact_type,
            "title": row.title,
            "content": row.content,
            "metadata_text": row.metadata_text,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in artifacts
    ]
    result["context_epochs"] = [
        {
            "id": row.id,
            "epoch_number": row.epoch_number,
            "status": row.status,
            "source_event_start": row.source_event_start,
            "compact_through_sequence": row.compact_through_sequence,
            "archive_sha256": row.archive_sha256,
            "rendered_context_chars": row.rendered_context_chars,
            "estimated_input_tokens": row.estimated_input_tokens,
            "model_name": row.model_name,
            "schema_version": row.schema_version,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in epochs
    ]
    return result


@router.get("/jobs/{job_id}/events")
def list_events(
    job_id: str,
    after: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _owned_job(db, job_id, user.id)
    rows = db.query(ResearchEvent).filter(
        ResearchEvent.job_id == job_id,
        ResearchEvent.sequence > max(0, after),
    ).order_by(ResearchEvent.sequence).limit(max(1, min(limit, 500))).all()
    return {
        "events": [
            {
                "id": row.id,
                "sequence": row.sequence,
                "event_type": row.event_type,
                "content": row.content,
                "meta_text": row.meta_text,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.post("/jobs/{job_id}/pause")
async def pause_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = _owned_job(db, job_id, user.id)
    if job.status == "completed":
        return _serialize_job(job)
    await research_agent_manager.pause(job_id)
    db.expire_all()
    return _serialize_job(_owned_job(db, job_id, user.id))


@router.post("/jobs/{job_id}/continue")
async def continue_job(
    job_id: str,
    payload: ContinueRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = _owned_job(db, job_id, user.id)
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="追加要求不能为空")
    add_research_instruction(job_id, message)
    job.status = "running"
    job.completed = False
    job.error = ""
    job.stage = "根据用户要求继续分析"
    db.commit()
    research_agent_manager.start(job_id)
    db.refresh(job)
    return _serialize_job(job)


@router.get("/jobs/{job_id}/versions/{version_id}/download")
def download_version(
    job_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = _owned_job(db, job_id, user.id)
    version = db.query(ResearchTextVersion).filter(
        ResearchTextVersion.id == version_id,
        ResearchTextVersion.job_id == job_id,
    ).first()
    if not version or not Path(version.file_path).is_file():
        raise HTTPException(status_code=404, detail="文本版本不存在")
    suffix = "original" if version.kind == "raw" else f"cleaned-v{version.version_number}"
    filename = f"{Path(job.original_filename).stem}-{suffix}.txt"
    return FileResponse(
        version.file_path,
        media_type="text/plain",
        filename=filename,
    )
