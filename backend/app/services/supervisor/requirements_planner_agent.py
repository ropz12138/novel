"""RequirementsPlannerAgent — 基于 LangGraph StateGraph + Tool-Calling 的需求规划子 Agent"""

from __future__ import annotations

import logging
from typing import Callable

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolNode
from sqlalchemy.orm import Session

from app.services.supervisor.sub_agent_base import chunk_to_ai_message, get_llm
from app.services.supervisor.requirements_planner_tools import REQUIREMENTS_PLANNER_TOOLS

logger = logging.getLogger(__name__)


class RequirementsPlannerState(MessagesState):
    message: str
    work_id: str | None
    session_id: str | None


SYSTEM_PROMPT = """你是一位需求分析专家。你的任务是：
1. 理解用户的写作需求
2. 读取相关上下文（作品信息、对话历史）
3. 分析需求，生成结构化的需求分析和任务清单
4. 如果需求不明确，列出需要澄清的问题

请使用你的工具来完成分析。"""


async def _requirements_planner_agent_node(state: RequirementsPlannerState) -> dict:
    llm = get_llm(temperature=0.2)
    llm_with_tools = llm.bind_tools(REQUIREMENTS_PLANNER_TOOLS)

    messages = state.get("messages", [])

    has_system = any(isinstance(m, SystemMessage) for m in messages)
    if not has_system:
        full_messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
    else:
        full_messages = messages

    aggregated = None
    async for chunk in llm_with_tools.astream(full_messages):
        aggregated = chunk if aggregated is None else aggregated + chunk

    if aggregated is None:
        raise RuntimeError("RequirementsPlannerAgent LLM 未返回任何流式分片")

    response = chunk_to_ai_message(aggregated)
    return {"messages": [response]}


def _should_continue(state: RequirementsPlannerState) -> str:
    messages = state.get("messages", [])
    if not messages:
        return END
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


class RequirementsPlannerAgent:
    """需求规划 Agent — 使用 LangGraph StateGraph 编排"""

    def __init__(self, emit: Callable):
        self.emit = emit

    def _build_graph(self):
        graph = StateGraph(RequirementsPlannerState)
        graph.add_node("agent", _requirements_planner_agent_node)
        graph.add_node("tools", ToolNode(REQUIREMENTS_PLANNER_TOOLS))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
        return graph.compile()

    async def plan(
        self,
        message: str,
        work_id: str | None,
        history: list[dict] | None,
        db: Session,
    ) -> dict:
        self.emit("stage_start", {"stage": "requirements_planner", "label": "需求澄清与任务规划"})

        graph = self._build_graph()
        config = {"configurable": {"db": db, "emit": self.emit}, "recursion_limit": 20}

        initial_state = {
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=f"请分析以下需求：{message}"),
            ],
            "message": message,
            "work_id": work_id,
            "session_id": None,
        }

        final_state = None
        tool_results_text = []

        async for event in graph.astream(initial_state, config=config):
            for node_name, node_output in event.items():
                if node_name == "tools":
                    tool_msgs = node_output.get("messages", [])
                    for tm in tool_msgs:
                        content = tm.content if hasattr(tm, "content") else str(tm)
                        tool_results_text.append(str(content))
                        self.emit("requirements_draft", {"chunk": str(content)[:200]})
            final_state = node_output

        # 从 analyze_requirements 工具返回的文本中提取结构化数据
        result = {
            "intent_summary": "",
            "questions": [],
            "todolist": [],
            "ready_to_execute": False,
        }

        combined_tool_text = "\n".join(tool_results_text)

        # 解析工具返回文本中的 questions（"- xxx" 格式）
        if "需要澄清的问题" in combined_tool_text:
            for line in combined_tool_text.split("\n"):
                line = line.strip()
                if line.startswith("- ") and len(line) > 2:
                    result["questions"].append(line[2:])
            result["ready_to_execute"] = False

        # 解析工具返回文本中的 todolist（"- xxx" 格式）
        if "生成了" in combined_tool_text and "条任务" in combined_tool_text:
            for line in combined_tool_text.split("\n"):
                line = line.strip()
                if line.startswith("- ") and len(line) > 2:
                    result["todolist"].append(line[2:])
            result["ready_to_execute"] = True

        # 从 LLM 最终回复中提取 intent_summary
        if final_state:
            messages = final_state.get("messages", [])
            for msg in reversed(messages):
                if hasattr(msg, "content") and msg.content and not getattr(msg, "tool_calls", None):
                    content = msg.content
                    # 尝试提取 intent_summary
                    if "intent_summary" in content:
                        import re
                        m = re.search(r"intent_summary[:：]\s*(.+?)(?:\n|$)", content)
                        if m:
                            result["intent_summary"] = m.group(1).strip()
                    # 如果工具层没解析到 questions，从最终回复兜底
                    if not result["questions"] and ("需要澄清" in content or "问题" in content):
                        result["intent_summary"] = result["intent_summary"] or content[:200]
                    break
            # 如果最终回复也没有 intent_summary，用第一条用户消息的摘要
            if not result["intent_summary"] and messages:
                result["intent_summary"] = f"需求澄清与任务规划（基于用户输入：{message[:50]}）"

        self.emit("requirements_ready", {
            "ready_to_execute": result["ready_to_execute"],
            "questions_count": len(result["questions"]),
            "tasks_count": len(result["todolist"]),
        })

        return result
