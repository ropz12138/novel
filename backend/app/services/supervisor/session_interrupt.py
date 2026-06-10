"""Supervisor 会话中断检测 — 供子 Agent / 长工具轮询。"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig
from sqlalchemy import text
from sqlalchemy.orm import Session

INTERRUPTED_USER_MESSAGE = "任务已被用户中断。"


class SessionInterruptedError(Exception):
    """当前 Supervisor 会话已被用户标记中断。"""


def is_session_interrupted(db: Session, session_id: str | None) -> bool:
    """读取中断标志。必须用原生 SQL，避免 ORM identity map 返回过期的 interrupted=False。"""
    if not session_id:
        return False
    value = db.execute(
        text("SELECT interrupted FROM supervisor_sessions WHERE id = :sid"),
        {"sid": session_id},
    ).scalar_one_or_none()
    return bool(value)


def check_session_interrupted(config: RunnableConfig | None) -> bool:
    if not config:
        return False
    configurable = config.get("configurable", {})
    db = configurable.get("db")
    session_id = configurable.get("supervisor_session_id")
    if db is None or not session_id:
        return False
    return is_session_interrupted(db, str(session_id))


def make_interrupt_checker(config: RunnableConfig | None):
    """返回可在流式 LLM 循环中轮询的中断检查函数。"""

    def _check() -> bool:
        return check_session_interrupted(config)

    return _check
