"""小说作品库与独立研究会话 API。"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models.research import ResearchArtifact, ResearchJob, ResearchMessage, ResearchMessageChapterReference, ResearchMessageWorkReference, ResearchSession, ResearchTextVersion
from models.user import User
from routers.auth import get_current_user
from services.research_chat import research_chat_service
from services.research_chapters import list_indexed_chapters, read_indexed_chapter
from services.research_text_tools import create_job_files

router = APIRouter(prefix="/research", tags=["research"])
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


class CreateSessionRequest(BaseModel):
    title: str = "新对话"


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    message: str
    work_id: str | None = None
    chapter_version_id: str | None = None
    chapter_index: int | None = None


def _serialize_work(work: ResearchJob) -> dict:
    return {"id": work.id, "original_filename": work.original_filename,
            "status": work.status, "stage": work.stage,
            "created_at": work.created_at.isoformat() if work.created_at else None}


def _serialize_session(session: ResearchSession) -> dict:
    return {"id": session.id, "title": session.title,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None}


def _serialize_message(message: ResearchMessage) -> dict:
    chapter_reference = None
    if message.chapter_reference is not None:
        version = message.chapter_reference.version
        chapter = read_indexed_chapter(version, message.chapter_reference.section_index)
        chapter_reference = {
            "work_id": version.job_id,
            "version_id": version.id,
            "section_index": chapter["section_index"],
            "number": chapter["number"],
            "title": chapter["title"],
            "heading": chapter["heading"],
        }
    return {"id": message.id, "role": message.role, "content": message.content,
            "sequence": message.sequence,
            "referenced_works": [{"id": ref.work.id, "filename": ref.work.original_filename}
                                 for ref in message.work_references],
            "chapter_reference": chapter_reference,
            "created_at": message.created_at.isoformat() if message.created_at else None}


def _serialize_artifact(row: ResearchArtifact) -> dict:
    return {"id": row.id, "artifact_type": row.artifact_type, "title": row.title,
            "content": row.content,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def _owned_work(db: Session, work_id: str, user_id: str) -> ResearchJob:
    work = db.query(ResearchJob).filter(ResearchJob.id == work_id, ResearchJob.user_id == user_id).first()
    if not work:
        raise HTTPException(status_code=404, detail="作品不存在")
    return work


def _owned_session(db: Session, session_id: str, user_id: str) -> ResearchSession:
    session = db.query(ResearchSession).filter(
        ResearchSession.id == session_id, ResearchSession.user_id == user_id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="对话不存在")
    return session


@router.post("/works")
async def upload_work(request: Request, filename: str = Query(..., min_length=1, max_length=500),
                      user: User = Depends(get_current_user)):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件不能超过100MB")
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件不能超过100MB")
    if not filename.lower().endswith(".txt"):
        raise HTTPException(status_code=400, detail="第一版仅支持TXT文件")
    try:
        return create_job_files(user.id, filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/works")
def list_works(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(ResearchJob).filter(ResearchJob.user_id == user.id).order_by(ResearchJob.created_at.desc()).all()
    return {"works": [_serialize_work(row) for row in rows]}


@router.get("/works/{work_id}/artifacts")
def list_work_artifacts(work_id: str, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    _owned_work(db, work_id, user.id)
    rows = db.query(ResearchArtifact).filter(ResearchArtifact.job_id == work_id).order_by(
        ResearchArtifact.created_at.desc()
    ).all()
    return {"artifacts": [_serialize_artifact(row) for row in rows]}


@router.get("/library")
def get_research_library(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    works = db.query(ResearchJob).filter(ResearchJob.user_id == user.id).order_by(
        ResearchJob.created_at.desc()
    ).all()
    return {"works": [
        {"id": work.id, "original_filename": work.original_filename,
         "artifacts": [_serialize_artifact(row) for row in (
             db.query(ResearchArtifact).filter(ResearchArtifact.job_id == work.id).order_by(
                 ResearchArtifact.created_at.desc()
             ).all()
         )]}
        for work in works
    ]}


@router.get("/works/{work_id}/versions")
def list_work_versions(work_id: str, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    work = _owned_work(db, work_id, user.id)
    rows = db.query(ResearchTextVersion).filter(ResearchTextVersion.job_id == work_id).order_by(
        ResearchTextVersion.version_number
    ).all()
    return {"versions": [
        {"id": row.id, "version_number": row.version_number, "kind": row.kind,
         "encoding": row.encoding, "active": row.id == work.active_version_id,
         "has_index": bool(row.index_path),
         "created_at": row.created_at.isoformat() if row.created_at else None}
        for row in rows
    ]}


def _owned_cleaned_version(
    db: Session, work_id: str, version_id: str, user_id: str,
) -> ResearchTextVersion:
    _owned_work(db, work_id, user_id)
    version = db.query(ResearchTextVersion).filter(
        ResearchTextVersion.id == version_id,
        ResearchTextVersion.job_id == work_id,
        ResearchTextVersion.kind == "cleaned",
    ).first()
    if not version:
        raise HTTPException(status_code=404, detail="整理版本不存在")
    return version


@router.get("/works/{work_id}/versions/{version_id}/chapters")
def list_version_chapters(work_id: str, version_id: str,
                          db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    version = _owned_cleaned_version(db, work_id, version_id, user.id)
    try:
        return {"chapters": list_indexed_chapters(version)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/works/{work_id}/versions/{version_id}/chapters/{section_index}")
def get_version_chapter(work_id: str, version_id: str, section_index: int,
                        db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    version = _owned_cleaned_version(db, work_id, version_id, user.id)
    try:
        return read_indexed_chapter(version, section_index)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions")
def create_session(payload: CreateSessionRequest, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    session = ResearchSession(user_id=user.id, title=(payload.title.strip() or "新对话")[:200])
    db.add(session)
    db.commit()
    db.refresh(session)
    return _serialize_session(session)


@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(ResearchSession).filter(ResearchSession.user_id == user.id).order_by(ResearchSession.updated_at.desc()).all()
    return {"sessions": [_serialize_session(row) for row in rows]}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = _owned_session(db, session_id, user.id)
    result = _serialize_session(session)
    result["messages"] = [_serialize_message(message) for message in session.messages]
    return result


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, payload: SendMessageRequest,
                       db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    session = _owned_session(db, session_id, user.id)
    if not payload.message:
        raise HTTPException(status_code=400, detail="消息不能为空")
    chapter_version = None
    if (payload.chapter_version_id is None) != (payload.chapter_index is None):
        raise HTTPException(status_code=400, detail="章节版本和章节索引必须同时提供")
    if payload.chapter_version_id is not None:
        chapter_version = db.query(ResearchTextVersion).join(
            ResearchJob, ResearchTextVersion.job_id == ResearchJob.id,
        ).filter(
            ResearchTextVersion.id == payload.chapter_version_id,
            ResearchTextVersion.kind == "cleaned",
            ResearchJob.user_id == user.id,
        ).first()
        if not chapter_version:
            raise HTTPException(status_code=404, detail="引用章节不存在")
        try:
            read_indexed_chapter(chapter_version, payload.chapter_index)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if payload.work_id and payload.work_id != chapter_version.job_id:
            raise HTTPException(status_code=400, detail="作品引用与章节引用不一致")
    resolved_work_id = chapter_version.job_id if chapter_version else payload.work_id
    work = _owned_work(db, resolved_work_id, user.id) if resolved_work_id else None
    maximum = db.query(func.max(ResearchMessage.sequence)).filter(ResearchMessage.session_id == session_id).scalar()
    user_message = ResearchMessage(session_id=session_id, role="user", content=payload.message,
                                   sequence=(maximum + 1) if maximum is not None else 0)
    db.add(user_message)
    db.flush()
    if work is not None:
        db.add(ResearchMessageWorkReference(message_id=user_message.id, work_id=work.id))
    if chapter_version is not None:
        db.add(ResearchMessageChapterReference(
            message_id=user_message.id,
            version_id=chapter_version.id,
            section_index=payload.chapter_index,
        ))
    if session.title == "新对话":
        session.title = payload.message[:50] + ("…" if len(payload.message) > 50 else "")
    session.updated_at = datetime.now(timezone.utc)
    db.commit()

    answer = await research_chat_service.reply(session_id)
    assistant_message = ResearchMessage(session_id=session_id, role="assistant", content=answer,
                                        sequence=user_message.sequence + 1)
    db.add(assistant_message)
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    return {"user_message": _serialize_message(user_message),
            "assistant_message": _serialize_message(assistant_message)}


@router.get("/works/{work_id}/versions/{version_id}/download")
def download_version(work_id: str, version_id: str, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    work = _owned_work(db, work_id, user.id)
    version = db.query(ResearchTextVersion).filter(ResearchTextVersion.id == version_id,
                                                  ResearchTextVersion.job_id == work_id).first()
    if not version or not Path(version.file_path).is_file():
        raise HTTPException(status_code=404, detail="文本版本不存在")
    return FileResponse(version.file_path, media_type="text/plain", filename=work.original_filename)
