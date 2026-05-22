"""EvaluationAgent — 基于 LangGraph StateGraph + Tool-Calling 的章节评估子 Agent

改造自原来的固定双路评估，现在 LLM 自主选择工具完成评估。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolNode
from sqlalchemy.orm import Session

from app.services.supervisor.evaluation_tools import EVALUATION_TOOLS
from app.services.supervisor.sub_agent_base import chunk_to_ai_message, get_llm

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent / "prompt_templates"


class EvaluationState(MessagesState):
    """EvaluationAgent 的状态"""
    work_id: str
    chapter_number: int
    chapter_content_override: str


def _build_evaluation_system_prompt(work_id: str, chapter_number: int) -> str:
    template = (PROMPT_DIR / "evaluation_agent_system.txt").read_text(encoding="utf-8")
    return template.format(work_id=work_id, chapter_number=chapter_number)


async def _evaluation_agent_node(state: EvaluationState) -> dict:
    llm = get_llm(temperature=0.2, streaming=False)
    llm_with_tools = llm.bind_tools(EVALUATION_TOOLS)

    messages = state.get("messages", [])

    has_system = any(isinstance(m, SystemMessage) for m in messages)
    if not has_system:
        system_prompt = _build_evaluation_system_prompt(
            work_id=state.get("work_id", ""),
            chapter_number=state.get("chapter_number", 0),
        )
        full_messages = [SystemMessage(content=system_prompt)] + messages
    else:
        full_messages = messages

    aggregated = None
    async for chunk in llm_with_tools.astream(full_messages):
        aggregated = chunk if aggregated is None else aggregated + chunk

    if aggregated is None:
        raise RuntimeError("EvaluationAgent LLM 未返回任何流式分片")

    response = chunk_to_ai_message(aggregated)
    return {"messages": [response]}


def _should_continue(state: EvaluationState) -> str:
    messages = state.get("messages", [])
    if not messages:
        return END
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


class EvaluationAgent:
    """章节评估 Agent — 使用 LangGraph StateGraph 编排"""

    def _build_graph(self):
        graph = StateGraph(EvaluationState)
        graph.add_node("agent", _evaluation_agent_node)
        graph.add_node("tools", ToolNode(EVALUATION_TOOLS))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
        return graph.compile()

    async def evaluate_chapter(
        self,
        *,
        db: Session,
        work_id: str,
        chapter_number: int,
        chapter_content_override: str = "",
    ) -> tuple[str, dict, dict]:
        """评估章节 — 通过 Tool-Calling 让 LLM 自主选择工具完成评估。"""
        from app.models.work_model import Chapter
        from app.schemas.evaluation_schema import RoleEvaluation
        from app.services.supervisor.sub_agent_base import get_llm

        emit = lambda e, d: None  # EvaluationAgent 的 emit 通过 config 传递

        graph = self._build_graph()
        config = {"configurable": {"db": db, "emit": emit}, "recursion_limit": 25}

        user_msg = f"请评估第{chapter_number}章"
        if chapter_content_override:
            user_msg += f"，以下是正文：\n{chapter_content_override}"

        system_prompt = _build_evaluation_system_prompt(
            work_id=work_id,
            chapter_number=chapter_number,
        )

        initial_state = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ],
            "work_id": work_id,
            "chapter_number": chapter_number,
            "chapter_content_override": chapter_content_override,
        }

        final_state = await graph.ainvoke(initial_state, config=config)

        # 提取工具结果中的评估数据（需完整 messages，不能用 astream 最后一帧增量）
        editor_result = {"total_score": 0, "issues": [], "suggestions": []}
        reader_result = {"total_score": 0, "issues": [], "suggestions": []}

        if final_state:
            messages = final_state.get("messages", [])
            for msg in messages:
                if hasattr(msg, "name"):
                    if msg.name == "evaluate_as_editor":
                        editor_result = _parse_eval_result(msg.content)
                    elif msg.name == "evaluate_as_reader":
                        reader_result = _parse_eval_result(msg.content)

        # 获取标题
        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        title = chapter.title if chapter else f"第{chapter_number}章"

        return title, editor_result, reader_result


def _parse_eval_result(content: str) -> dict:
    """从工具返回的文本中解析评估结果"""
    import re
    score_match = re.search(r"(\d+)/60", content)
    total_score = int(score_match.group(1)) if score_match else 0

    issues = []
    suggestions = []

    issues_match = re.search(r"问题[：:](.+?)(?:。建议|$)", content)
    if issues_match:
        issues = [i.strip() for i in issues_match.group(1).split("；") if i.strip()]

    suggestions_match = re.search(r"建议[：:](.+?)$", content)
    if suggestions_match:
        suggestions = [s.strip() for s in suggestions_match.group(1).split("；") if s.strip()]

    return {
        "total_score": total_score,
        "issues": issues,
        "suggestions": suggestions,
    }
