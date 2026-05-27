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
    chapter_number: int | None
    chapter_content_override: str
    user_message: str


def _build_evaluation_system_prompt(
    work_id: str,
    chapter_number: int | None,
    user_message: str,
) -> str:
    template = (PROMPT_DIR / "evaluation_agent_system.txt").read_text(encoding="utf-8")
    if chapter_number is None:
        target_description = (
            "未由系统固定；请从 Supervisor 下派任务中判断目标章节，"
            "并在每次评估相关工具调用时显式传入 chapter_number。"
        )
        boundary_rule = (
            "如果任务要求评估第N章，调用评估工具时就必须传入 chapter_number=N；"
            "不要因为文本中出现其他章节引用而改成别的章节。"
        )
    else:
        target_description = f"第{chapter_number}章"
        boundary_rule = f"当前任务只评估第{chapter_number}章，不得改评其他章节。"
    return template.format(
        work_id=work_id,
        target_description=target_description,
        boundary_rule=boundary_rule,
        user_message=user_message,
    )


async def _evaluation_agent_node(state: EvaluationState) -> dict:
    llm = get_llm(temperature=0.2, streaming=False)
    llm_with_tools = llm.bind_tools(EVALUATION_TOOLS)

    messages = state.get("messages", [])

    has_system = any(isinstance(m, SystemMessage) for m in messages)
    if not has_system:
        system_prompt = _build_evaluation_system_prompt(
            work_id=state.get("work_id", ""),
            chapter_number=state.get("chapter_number"),
            user_message=state.get("user_message", ""),
        )
        full_messages = [SystemMessage(content=system_prompt)] + messages
    else:
        full_messages = messages

    msg_summary: list[str] = []
    for i, m in enumerate(full_messages):
        role = getattr(m, "type", type(m).__name__)
        content_len = len(getattr(m, "content", "") or "")
        tc_count = len(getattr(m, "tool_calls", []) or [])
        msg_summary.append(f"[{i}]{role}:len={content_len},tc={tc_count}")
    logger.info(
        "evaluation.agent_node input_messages=%d summary=[%s]",
        len(full_messages),
        " | ".join(msg_summary),
    )

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
        chapter_number: int | None = None,
        user_message: str = "",
        chapter_content_override: str = "",
        history: list[str] | None = None,
        base_configurable: dict | None = None,
    ) -> tuple[str, str, str, str]:
        """评估章节 — 通过 Tool-Calling 让 LLM 自主选择工具完成评估。

        Args:
            history: 之前评估的历史文本列表（子 agent 记忆）

        Returns:
            (title, editor_text, reader_text, sync_text) 全部为纯文本
        """
        from app.models.work_model import Chapter

        graph = self._build_graph()
        configurable = dict(base_configurable or {})
        configurable.update({
            "db": db,
            "emit": configurable.get("emit") or (lambda e, d: None),
            "work_id": work_id,
            "chapter_number": chapter_number,
        })
        config = {
            "configurable": configurable,
            "recursion_limit": 100,
        }

        if user_message.strip():
            user_msg = user_message.strip()
        elif chapter_number is not None:
            user_msg = f"请评估第{chapter_number}章"
        else:
            user_msg = "请按 Supervisor 下派任务评估目标章节。"
        if chapter_content_override:
            user_msg += f"\n\n以下是正文草稿：\n{chapter_content_override}"

        system_prompt = _build_evaluation_system_prompt(
            work_id=work_id,
            chapter_number=chapter_number,
            user_message=user_msg,
        )

        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_msg)]
        if history:
            for h in history:
                messages.append(HumanMessage(content=f"之前的评估上下文：\n{h}"))

        initial_state = {
            "messages": messages,
            "work_id": work_id,
            "chapter_number": chapter_number,
            "chapter_content_override": chapter_content_override,
            "user_message": user_msg,
        }

        final_state = await graph.ainvoke(initial_state, config=config)

        editor_text = ""
        reader_text = ""
        sync_text = ""

        if final_state:
            messages = final_state.get("messages", [])
            for msg in messages:
                if hasattr(msg, "name"):
                    if msg.name == "evaluate_as_editor":
                        editor_text = msg.content or ""
                    elif msg.name == "evaluate_as_reader":
                        reader_text = msg.content or ""
                    elif msg.name == "evaluate_chapter_outline_sync":
                        sync_text = msg.content or ""

        title = "章节评估"
        if chapter_number is not None:
            chapter = db.query(Chapter).filter_by(
                work_id=work_id, chapter_number=chapter_number
            ).first()
            title = chapter.title if chapter else f"第{chapter_number}章"

        return title, editor_text, reader_text, sync_text
