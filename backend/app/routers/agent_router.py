"""Agent SSE router for chapter writing agent."""

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.agent_model import AgentState
from app.schemas.agent_schema import AgentResumeRequest, AgentStartRequest
from app.services.agent.graph import ChapterAgentGraph

router = APIRouter(prefix="/agent", tags=["agent"])


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{work_id}/chapters/{chapter_number}/start")
async def start_agent(
    work_id: str,
    chapter_number: int,
    payload: AgentStartRequest,
    db: Session = Depends(get_db),
):
    """Start a new agent session for a chapter. Returns SSE stream."""
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: str, data: dict):
        queue.put_nowait((event, data))

    async def event_generator():
        graph = ChapterAgentGraph(work_id, chapter_number, db, emit)

        # Run the agent in a background task
        async def run():
            try:
                await graph.start(instruction=payload.instruction)
            except Exception as exc:
                emit("error", {"message": str(exc)})
            finally:
                await queue.put(None)  # sentinel

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
):
    """Resume a paused agent session. Returns SSE stream."""
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: str, data: dict):
        queue.put_nowait((event, data))

    async def event_generator():
        graph = ChapterAgentGraph(work_id, chapter_number, db, emit)

        async def run():
            try:
                await graph.resume(action=payload.action, instruction=payload.instruction)
            except Exception as exc:
                emit("error", {"message": str(exc)})
            finally:
                await queue.put(None)  # sentinel

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
):
    """Get current agent state for a chapter."""
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
