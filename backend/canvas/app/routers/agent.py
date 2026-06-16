"""Agent对话API"""
import json
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.agents.supervisor import supervisor_agent
from app.services.agents.outline_agent import outline_agent
from app.services.agents.chapter_agent import chapter_agent

router = APIRouter(tags=["agent"])


class ChatRequest(BaseModel):
    message: str
    agent_type: str = "supervisor"  # supervisor/outline/chapter
    work_id: Optional[str] = None  # 作品ID
    chapter_context: str = ""


class ChatResponse(BaseModel):
    success: bool
    message: str
    error: Optional[str] = None


def _sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/agent/chat/stream")
async def chat_with_agent_stream(
    request: ChatRequest,
    user: User = Depends(get_current_user),
):
    """与Agent对话（SSE流式）"""
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: str, data: dict):
        await queue.put((event, data))

    async def run_agent():
        try:
            context = {
                "user_id": user.id,
                "work_id": request.work_id,
            }

            if request.agent_type == "supervisor":
                result = await supervisor_agent.run(request.message, context, emit=emit)
            elif request.agent_type == "outline":
                result = await outline_agent.run(request.message, context)
            elif request.agent_type == "chapter":
                result = await chapter_agent.run(request.message, context, request.chapter_context)
            else:
                result = {"success": False, "error": f"未知的Agent类型: {request.agent_type}"}
                await emit("error", {"message": result["error"]})
        except Exception as e:
            await emit("error", {"message": str(e)})
        finally:
            await queue.put(None)

    async def event_generator():
        task = asyncio.create_task(run_agent())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                yield _sse_format(event, data)
        except asyncio.CancelledError:
            task.cancel()
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/agent/chat", response_model=ChatResponse)
async def chat_with_agent(
    request: ChatRequest,
    user: User = Depends(get_current_user),
):
    """与Agent对话"""
    try:
        # 构建上下文
        context = {
            "user_id": user.id,
            "work_id": request.work_id,
        }

        if request.agent_type == "supervisor":
            result = await supervisor_agent.run(request.message, context)
        elif request.agent_type == "outline":
            result = await outline_agent.run(request.message, context)
        elif request.agent_type == "chapter":
            result = await chapter_agent.run(request.message, context, request.chapter_context)
        else:
            raise HTTPException(status_code=400, detail=f"未知的Agent类型: {request.agent_type}")

        return ChatResponse(
            success=result.get("success", False),
            message=result.get("message", ""),
            error=result.get("error"),
        )

    except Exception as e:
        return ChatResponse(
            success=False,
            message="",
            error=str(e),
        )


@router.get("/agent/agents")
async def list_agents(user: User = Depends(get_current_user)):
    """获取可用的Agent列表"""
    return {
        "agents": [
            {
                "id": "supervisor",
                "name": "主控Agent",
                "description": "智能调度，根据意图选择合适的Agent",
            },
            {
                "id": "outline",
                "name": "大纲Agent",
                "description": "创建和编辑故事大纲、生成角色卡",
            },
            {
                "id": "chapter",
                "name": "章节Agent",
                "description": "生成和编辑章节内容",
            },
            {
                "id": "evaluation",
                "name": "评估Agent",
                "description": "评估内容质量、检查一致性",
            },
        ]
    }
