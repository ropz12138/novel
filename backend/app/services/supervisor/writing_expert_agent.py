"""WritingExpertAgent — 基于 LangGraph StateGraph + Tool-Calling 的写作专家子 Agent"""

from __future__ import annotations

import logging
from typing import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolNode
from sqlalchemy.orm import Session

from app.services.supervisor.sub_agent_base import (
    astream_agent_llm_to_message,
    bind_agent_llm_with_tools,
    get_llm,
)
from app.services.supervisor.writing_expert_tools import WRITING_EXPERT_TOOLS

logger = logging.getLogger(__name__)


class WritingExpertState(MessagesState):
    problem_type: str
    genre_tags: list[str]
    constraints: list[str]
    chapter_goal: str
    chapter_number: int | None


SYSTEM_PROMPT = """你是一位写作专家，擅长为小说写作提供具体可落地的建议。

你的任务是：
1. 根据问题类型和题材，查询相关的写作技巧
2. 生成针对性的建议方案
3. 推荐最佳方案并给出章节改写指令

问题类型可能包括：conflict_event（冲突事件）、hook_design（章末钩子）、pacing_fix（节奏修复）、character_tension（人物张力）、dialogue_upgrade（对话升级）

请使用你的工具完成分析和建议生成。"""


def _make_writing_expert_agent_node(*, emit):
    async def _writing_expert_agent_node(state: WritingExpertState) -> dict:
        llm = get_llm(temperature=0.5)
        llm_with_tools = bind_agent_llm_with_tools(llm, WRITING_EXPERT_TOOLS)

        messages = state.get("messages", [])

        has_system = any(isinstance(m, SystemMessage) for m in messages)
        if not has_system:
            full_messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
        else:
            full_messages = messages

        response = await astream_agent_llm_to_message(
            llm_with_tools,
            full_messages,
            emit=emit,
            stream_event="thinking_stream",
        )
        return {"messages": [response]}

    return _writing_expert_agent_node


def _should_continue(state: WritingExpertState) -> str:
    messages = state.get("messages", [])
    if not messages:
        return END
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


class WritingExpertAgent:
    """写作专家 Agent — 使用 LangGraph StateGraph 编排"""

    def __init__(self, emit: Callable):
        self.emit = emit

    def _build_graph(self):
        graph = StateGraph(WritingExpertState)
        graph.add_node("agent", _make_writing_expert_agent_node(emit=self.emit))
        graph.add_node("tools", ToolNode(WRITING_EXPERT_TOOLS))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
        return graph.compile()

    async def advise(
        self,
        db: Session,
        problem_type: str,
        genre_tags: list[str],
        constraints: list[str] | None = None,
        chapter_goal: str = "",
        chapter_number: int | None = None,
        count: int = 8,
        history: list[str] | None = None,
    ) -> dict:
        self.emit("stage_start", {"stage": "writing_expert", "label": "写作专家微咨询"})

        graph = self._build_graph()
        config = {"configurable": {"db": db, "emit": self.emit}, "recursion_limit": 20}

        user_msg = f"请为「{'、'.join(genre_tags)}」题材的小说提供关于「{problem_type}」的建议"
        if chapter_goal:
            user_msg += f"，章节目标是：{chapter_goal}"

        messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_msg)]
        if history:
            for h in history:
                messages.append(HumanMessage(content=f"之前的咨询上下文：\n{h}"))

        initial_state = {
            "messages": messages,
            "problem_type": problem_type,
            "genre_tags": genre_tags,
            "constraints": constraints or [],
            "chapter_goal": chapter_goal,
            "chapter_number": chapter_number,
        }

        final_state = None
        async for event in graph.astream(initial_state, config=config):
            for node_name, node_output in event.items():
                pass
            final_state = node_output

        # 从工具结果中提取 payload
        payload = {
            "problem_type": problem_type,
            "genre_tags": genre_tags,
            "options": [],
            "recommended_pick": {},
            "apply_prompt_for_chapter_agent": "",
        }

        if final_state:
            messages = final_state.get("messages", [])
            for msg in reversed(messages):
                if hasattr(msg, "name") and msg.name == "generate_advice":
                    content = msg.content if hasattr(msg, "content") else str(msg)
                    # 简单提取
                    payload["apply_prompt_for_chapter_agent"] = content
                    break

        self.emit("writing_expert_done", payload)
        return payload
