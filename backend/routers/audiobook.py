# -*- coding: utf-8 -*-
"""Stream paragraph audio with bounded parts for long paragraphs."""
import hashlib
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models.node import Node
from models.user import User
from models.work import CanvasWork
from routers.auth import get_current_user, require_admin
from schemas.tts_settings import TtsSettings
from services.tts_settings import read_tts_settings, save_tts_settings
from services.audiobook_text import line_is_speakable, speech_text, split_audiobook_lines, audiobook_paragraph_parts
from services.tts import stream_speech

router = APIRouter(tags=["audiobook"])


@router.get("/tts-settings", response_model=TtsSettings)
def get_tts_settings(current_user: User = Depends(require_admin)):
    return read_tts_settings()


@router.put("/tts-settings", response_model=TtsSettings)
def put_tts_settings(payload: TtsSettings, current_user: User = Depends(require_admin)):
    try:
        return save_tts_settings(payload)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="无法保存朗读设置") from exc


class AudiobookLineRequest(BaseModel):
    line_index: int = Field(ge=0)
    chunk_index: int = Field(default=0, ge=0)
    content_sha256: str | None = None


@router.post("/works/{work_id}/nodes/{node_id}/audiobook")
@router.post("/works/{work_id}/nodes/{node_id}/audiobook-line")
async def read_audiobook_line(
    work_id: str,
    node_id: str,
    body: AudiobookLineRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    work = db.query(CanvasWork).filter(
        CanvasWork.id == work_id,
        CanvasWork.user_id == current_user.id,
    ).first()
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    node = db.query(Node).filter(Node.id == node_id, Node.work_id == work_id).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    if node.type != "chapter":
        raise HTTPException(status_code=400, detail="not a chapter")
    content = node.content or ""
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if body.content_sha256 is not None and body.content_sha256 != content_sha256:
        raise HTTPException(status_code=409, detail="章节正文已变化，请重新开始朗读")
    lines = split_audiobook_lines(content)
    if body.line_index >= len(lines):
        raise HTTPException(status_code=400, detail="line index out of range")
    paragraph_scope = request.url.path.endswith("/audiobook")
    chunk_headers = {}
    if paragraph_scope:
        parts = audiobook_paragraph_parts(content, body.line_index)
        if body.chunk_index >= len(parts):
            raise HTTPException(status_code=400, detail="chunk index out of range")
        part = parts[body.chunk_index]
        start = sum(len(item["text"]) for item in parts[:body.chunk_index])
        speech = part["text"]
        chunk_headers["X-Audio-Chunk"] = json.dumps({
            "index": body.chunk_index, "count": len(parts), "line_index": part["line_index"],
            "start": start, "end": start + len(speech), "content_sha256": content_sha256,
        })
    else:
        if body.chunk_index:
            raise HTTPException(status_code=400, detail="chunk index requires the paragraph endpoint")
        speech = speech_text(lines[body.line_index])
    if not line_is_speakable(speech):
        raise HTTPException(status_code=400, detail="line has no speech")
    stream = stream_speech(speech)
    try:
        first = await anext(stream)
    except Exception as exc:
        await stream.aclose()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def audio_chunks():
        try:
            yield first
            async for pcm in stream:
                yield pcm
        finally:
            await stream.aclose()

    return StreamingResponse(
        content=audio_chunks(),
        media_type="application/octet-stream",
        headers={
            **chunk_headers,
            "X-Audio-Format": "pcm",
            "X-Audio-Scope": "paragraph" if paragraph_scope else "line",
            "X-Audio-Sample-Rate": str(settings.tts_sample_rate),
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
