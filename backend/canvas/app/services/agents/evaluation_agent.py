"""评估Agent - 评估内容质量"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Callable, Optional, Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app.services.agents.llm import get_llm, bind_tools_to_llm, should_continue
from app.services.agents.tools import get_evaluation_agent_tools

logger = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).parent / "prompts"


# 全局context存储
_current_context: Dict[str, Any] = {}


def set_evaluation_context(context: Dict[str, Any]):
    """设置当前上下文"""
    global _current_context
    _current_context = context


def get_evaluation_context() -> Dict[str, Any]:
    """获取当前上下文"""
    return _current_context


class EvaluationAgentState(MessagesState):
    """评估Agent状态"""
    user_message: str = ""
    canvas_overview: str = ""


class EvaluationAgent:
    """评估Agent - 使用LangGraph StateGraph编排"""

    def __init__(self, emit: Optional[Callable] = None):
        self.emit = emit

    def _build_system_prompt(self, user_message: str, canvas_overview: str) -> str:
        """构建系统提示"""
        template_path = PROMPT_DIR / "evaluation_agent_system.txt"
        template = template_path.read_text(encoding="utf-8")
        return template.format(
            canvas_overview=canvas_overview,
            user_message=user_message,
        )

    def _build_graph(self):
        """构建LangGraph"""
        tools = get_evaluation_agent_tools()
        tool_node = ToolNode(tools)

        llm = get_llm(temperature=0.7)
        llm_with_tools = bind_tools_to_llm(llm, tools)

        async def agent_node(state: EvaluationAgentState):
            """Agent节点"""
            messages = state["messages"]

            if self.emit:
                await self.emit("thinking", {"status": "评估Agent思考中..."})

            response = await llm_with_tools.ainvoke(messages)
            return {"messages": [response]}

        graph = StateGraph(EvaluationAgentState)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", tool_node)

        graph.set_entry_point("agent")
        graph.add_conditional_edges(
            "agent",
            should_continue,
            {
                "tools": "tools",
                "end": END,
            }
        )
        graph.add_edge("tools", "agent")

        return graph.compile()

    async def run(self, user_message: str, canvas_overview: str = "", work_id: str = None) -> dict:
        """运行评估Agent"""
        try:
            # 设置上下文
            set_evaluation_context({"work_id": work_id})

            graph = self._build_graph()

            system_prompt = self._build_system_prompt(user_message, canvas_overview)

            initial_state = {
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                ],
                "user_message": user_message,
                "canvas_overview": canvas_overview,
            }

            final_state = await graph.ainvoke(initial_state, config={"recursion_limit": 50})

            last_message = final_state["messages"][-1]
            return {
                "success": True,
                "message": last_message.content if hasattr(last_message, "content") else str(last_message),
            }

        except asyncio.CancelledError:
            logger.info("EvaluationAgent cancelled (client disconnected)")
            return {"success": False, "error": "cancelled"}

        except Exception as e:
            logger.error(f"EvaluationAgent error: {e}")
            return {
                "success": False,
                "error": str(e),
            }


# 单例
evaluation_agent = EvaluationAgent()
