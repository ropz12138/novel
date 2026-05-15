"""SupervisorAgent 的 LangGraph State 定义"""

from __future__ import annotations

from typing import TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import MessagesState


class SupervisorState(MessagesState):
    """SupervisorAgent 在 LangGraph StateGraph 中传递的状态。

    继承 MessagesState 以支持 LangGraph 内置的 messages 管理。
    """

    # 作品上下文
    work_id: str
    session_id: str

    # SSE emit 回调 — 不参与 state 序列化，仅在运行时使用
    # 通过 RunnableConfig.configurable 传递
    # emit: Callable[[str, dict], None]

    # 工具执行阶段追踪（用于 SSE 事件）
    current_tool: str
    tool_results: list[dict]
