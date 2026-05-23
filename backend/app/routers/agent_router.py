"""Agent SSE router for chapter writing agent."""

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.agent_model import AgentState
from app.models.work_model import Chapter, User, Work
from app.schemas.agent_schema import AgentResumeRequest, AgentStartRequest
from app.services.agent.graph import ChapterAgentGraph
from app.services.agent_log_service import log_event, new_session_id

router = APIRouter(prefix="/agent", tags=["agent"])


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _make_logging_emit(emit, *, work_id: str, session_id: str, chapter_number: int, db_factory):
    """Wrap emit to log key agent events. Aggregates streaming chunks."""
    thinking_buf = []
    write_buf = []

    # Key events that should be logged as discrete entries
    LOG_EVENTS = {
        "stage_start", "thinking_done", "title_proposed",
        "outline_proposal", "outline_updated",
        "write_done", "saved", "done", "error",
        "need_confirm", "characters_updated",
        "plan_done",
        "queries_needed",
    }

    def logging_emit(event: str, data: dict):
        # Forward to SSE queue
        emit(event, data)

        # Buffer streaming chunks
        if event == "thinking_stream":
            thinking_buf.append(data.get("chunk", ""))
            return
        if event == "write_stream":
            write_buf.append(data.get("chunk", ""))
            return
        if event == "plan_stream":
            return  # Don't log plan stream chunks individually

        # Log query results individually (they are discrete)
        if event == "query_result":
            try:
                db = db_factory()
                log_event(db, work_id=work_id, session_id=session_id,
                          session_type="agent_writing", role="tool",
                          content=f"查询: {data.get('source', '')} — {data.get('summary', '')[:200]}",
                          chapter_number=chapter_number,
                          meta={"event": event, **data})
                db.close()
            except Exception:
                pass
            return

        # Flush buffers when stage completes
        if event == "stage_start":
            # Log previous stage's buffered content before resetting
            _flush_buffers(db_factory, work_id, session_id, chapter_number, thinking_buf, write_buf)

        # Log key events
        if event in LOG_EVENTS:
            try:
                db = db_factory()
                role = "assistant" if event in ("thinking_done", "write_done", "title_proposed") else "event"
                content = data.get("message", "") or data.get("title", "") or data.get("reason", "") or ""
                if event == "stage_start":
                    content = f"进入阶段: {data.get('label', data.get('stage', ''))}"
                elif event == "need_confirm":
                    content = f"等待确认: {data.get('type', '')}"
                    if data.get("title"):
                        content += f" | 标题: {data['title']}"
                log_event(db, work_id=work_id, session_id=session_id,
                          session_type="agent_writing", role=role,
                          content=content, chapter_number=chapter_number,
                          meta={"event": event, **{k: v for k, v in data.items() if k != "chunk"}})
                db.close()
            except Exception:
                pass

    def _flush_buffers(db_factory, work_id, session_id, chapter_number, thinking_buf, write_buf):
        if thinking_buf:
            try:
                db = db_factory()
                log_event(db, work_id=work_id, session_id=session_id,
                          session_type="agent_writing", role="assistant",
                          content="".join(thinking_buf),
                          chapter_number=chapter_number,
                          meta={"event": "thinking_stream_aggregated"})
                db.close()
            except Exception:
                pass
            thinking_buf.clear()
        if write_buf:
            try:
                db = db_factory()
                log_event(db, work_id=work_id, session_id=session_id,
                          session_type="agent_writing", role="assistant",
                          content="".join(write_buf)[:5000],
                          chapter_number=chapter_number,
                          meta={"event": "write_stream_aggregated",
                                "total_chars": len("".join(write_buf))})
                db.close()
            except Exception:
                pass
            write_buf.clear()

    return logging_emit


@router.post("/{work_id}/chapters/{chapter_number}/start")
async def start_agent(
    work_id: str,
    chapter_number: int,
    payload: AgentStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start a new agent session for a chapter. Returns SSE stream."""
    work = db.query(Work).filter_by(id=work_id, user_id=current_user.id).first()
    if not work:
        return StreamingResponse(
            iter([_sse_format("error", {
                "message": "作品不存在"
            })]),
            media_type="text/event-stream",
        )

    # Validate: can only write the next sequential chapter, or modify an existing one
    existing = db.query(Chapter).filter_by(
        work_id=work_id, chapter_number=chapter_number
    ).first()

    if not existing:
        max_chapter = db.query(Chapter).filter_by(work_id=work_id).order_by(
            Chapter.chapter_number.desc()
        ).first()
        expected_next = (max_chapter.chapter_number + 1) if max_chapter else 1
        if chapter_number != expected_next:
            return StreamingResponse(
                iter([_sse_format("error", {
                    "message": f"只能按顺序写新章节。当前应写第{expected_next}章，不能跳到第{chapter_number}章。"
                })]),
                media_type="text/event-stream",
            )

    session_id = new_session_id()

    # Log user instruction
    log_event(db, work_id=work_id, session_id=session_id,
              session_type="agent_writing", role="user",
              content=payload.instruction or "(开始写作)",
              chapter_number=chapter_number,
              meta={"action": "start"})

    queue: asyncio.Queue = asyncio.Queue()

    from app.core.database import SessionLocal
    logging_emit = _make_logging_emit(
        lambda e, d: queue.put_nowait((e, d)),
        work_id=work_id, session_id=session_id,
        chapter_number=chapter_number, db_factory=SessionLocal,
    )

    async def event_generator():
        graph = ChapterAgentGraph(
            work_id, chapter_number, db, logging_emit,
            auto_mode=payload.auto_mode,
        )

        async def run():
            try:
                await graph.start(instruction=payload.instruction)
            except Exception as exc:
                logging_emit("error", {"message": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())

        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield _sse_format(event, data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{work_id}/chapters/{chapter_number}/resume")
async def resume_agent(
    work_id: str,
    chapter_number: int,
    payload: AgentResumeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resume a paused agent session. Returns SSE stream."""
    work = db.query(Work).filter_by(id=work_id, user_id=current_user.id).first()
    if not work:
        return StreamingResponse(
            iter([_sse_format("error", {"message": "作品不存在"})]),
            media_type="text/event-stream",
        )
    session_id = new_session_id()

    # Log user action
    log_event(db, work_id=work_id, session_id=session_id,
              session_type="agent_writing", role="user",
              content=payload.instruction or f"({payload.action})",
              chapter_number=chapter_number,
              meta={"action": payload.action})

    queue: asyncio.Queue = asyncio.Queue()

    from app.core.database import SessionLocal
    logging_emit = _make_logging_emit(
        lambda e, d: queue.put_nowait((e, d)),
        work_id=work_id, session_id=session_id,
        chapter_number=chapter_number, db_factory=SessionLocal,
    )

    async def event_generator():
        graph = ChapterAgentGraph(work_id, chapter_number, db, logging_emit)

        async def run():
            try:
                await graph.resume(action=payload.action, instruction=payload.instruction)
            except Exception as exc:
                logging_emit("error", {"message": str(exc)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(run())

        while True:
            item = await queue.get()
            if item is None:
                break
            event, data = item
            yield _sse_format(event, data)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{work_id}/chapters/{chapter_number}/status")
def get_agent_status(
    work_id: str,
    chapter_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current agent state for a chapter."""
    work = db.query(Work).filter_by(id=work_id, user_id=current_user.id).first()
    if not work:
        return {"status": "idle", "stage": "idle"}
    agent = db.query(AgentState).filter_by(
        work_id=work_id, chapter_number=chapter_number
    ).first()
    if not agent:
        return {"status": "idle", "stage": "idle"}
    return {
        "status": agent.status,
        "stage": agent.stage,
        "chapter_title": agent.chapter_title,
        "chapter_content_preview": agent.chapter_content[:200] if agent.chapter_content else "",
        "thinking_notes": agent.thinking_notes[:300] if agent.thinking_notes else "",
    }
