"""Todolist 工具 — write_todolist / update_todolist"""
import asyncio
import logging
from functools import partial
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from services.todo_service import update_todolist as _update_todolist_service
from services.todo_service import write_todolist as _write_todolist_service

logger = logging.getLogger(__name__)


def _get_db():
    from database import SessionLocal
    return SessionLocal()


def _get_session_id():
    try:
        from services.agents.supervisor import get_context
        return get_context().get("session_id")
    except Exception:
        return None


def _get_emit():
    try:
        from services.agents.supervisor import get_context
        return get_context().get("emit")
    except Exception:
        return None


async def _emit_events(events: list[tuple[str, dict]]) -> None:
    emit = _get_emit()
    if not emit:
        return
    for event, data in events:
        try:
            await emit(event, data)
        except Exception:
            logger.warning("todo_tools emit %s 失败", event, exc_info=True)


class WriteTodolistInput(BaseModel):
    tasks: list[str] = Field(description="自然语言任务列表，每条只描述「做什么」，不写工具名或参数。")


class UpdateTodolistInput(BaseModel):
    action: str = Field(description="操作类型：complete（打勾完成）/ add（追加）/ edit（改文案）/ remove（删除未完成任务）")
    task_id: Optional[str] = Field(default=None, description="任务编号，如 T1；complete / edit / remove 时必填")
    task: Optional[str] = Field(default=None, description="edit 时的新任务文案")
    tasks: Optional[list[str]] = Field(default=None, description="add 时要追加的任务文案列表")


def _write_todolist_sync(tasks: list[str]):
    session_id = _get_session_id()
    db = _get_db()
    try:
        return _write_todolist_service(session_id, tasks, db)
    finally:
        db.close()


def _update_todolist_sync(
    action: str,
    task_id: Optional[str] = None,
    task: Optional[str] = None,
    tasks: Optional[list[str]] = None,
):
    session_id = _get_session_id()
    db = _get_db()
    try:
        return _update_todolist_service(
            session_id,
            action,
            db,
            task_id=task_id,
            task=task,
            tasks=tasks,
        )
    finally:
        db.close()


async def _write_todolist_async(tasks: list[str]) -> str:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_write_todolist_sync, tasks))
    await _emit_events(result.events)
    return result.message


async def _update_todolist_async(
    action: str,
    task_id: Optional[str] = None,
    task: Optional[str] = None,
    tasks: Optional[list[str]] = None,
) -> str:
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        partial(_update_todolist_sync, action, task_id, task, tasks),
    )
    await _emit_events(result.events)
    return result.message


write_todolist = StructuredTool.from_function(
    coroutine=_write_todolist_async,
    name="write_todolist",
    description=(
        "收到可执行的用户需求后，必须先创建任务清单再逐项执行。"
        "tasks 为自然语言字符串列表，每条只写「做什么」，"
        "禁止写工具名、坐标、node_id 等「怎么做」的内容；通常 1–4 条。"
    ),
    args_schema=WriteTodolistInput,
)

update_todolist = StructuredTool.from_function(
    coroutine=_update_todolist_async,
    name="update_todolist",
    description=(
        "更新任务清单。action=complete 打勾完成任务；add 追加 pending 任务；"
        "edit 修改未完成任务文案；remove 删除未完成任务。"
    ),
    args_schema=UpdateTodolistInput,
)

todo_tools = [write_todolist, update_todolist]
