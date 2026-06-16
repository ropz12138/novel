"""章节Agent - 生成和编辑章节内容"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Callable, Optional, Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from app.services.agents.llm import get_llm, bind_tools_to_llm, should_continue
from app.services.agents.tools import get_chapter_agent_tools

logger = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).parent / "prompts"


# 全局context存储
_current_context: Dict[str, Any] = {}


def set_chapter_context(context: Dict[str, Any]):
    """设置当前上下文"""
    global _current_context
    _current_context = context


def get_chapter_context() -> Dict[str, Any]:
    """获取当前上下文"""
    return _current_context


class ChapterAgentState(MessagesState):
    """章节Agent状态"""
    user_message: str = ""
    chapter_context: str = ""


class ChapterAgent:
    """章节Agent - 使用LangGraph StateGraph编排"""

    def __init__(self, emit: Optional[Callable] = None):
        self.emit = emit

    def _build_system_prompt(self, user_message: str, chapter_context: str) -> str:
        """构建系统提示"""
        template_path = PROMPT_DIR / "chapter_agent_system.txt"
        template = template_path.read_text(encoding="utf-8")
        return template.format(
            chapter_context=chapter_context,
            user_message=user_message,
        )

    def _build_graph(self):
        """构建LangGraph"""
        tools = get_chapter_agent_tools()
        tool_node = ToolNode(tools)

        llm = get_llm(temperature=0.7)
        llm_with_tools = bind_tools_to_llm(llm, tools)

        async def agent_node(state: ChapterAgentState):
            """Agent节点"""
            messages = state["messages"]

            if self.emit:
                await self.emit("thinking", {"status": "章节Agent思考中..."})

            response = await llm_with_tools.ainvoke(messages)
            return {"messages": [response]}

        graph = StateGraph(ChapterAgentState)
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

    async def run(self, user_message: str, chapter_context: str = "", work_id: str = None) -> dict:
        """运行章节Agent"""
        try:
            # 设置上下文
            set_chapter_context({"work_id": work_id})

            graph = self._build_graph()

            system_prompt = self._build_system_prompt(user_message, chapter_context)

            initial_state = {
                "messages": [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_message),
                ],
                "user_message": user_message,
                "chapter_context": chapter_context,
            }

            final_state = await graph.ainvoke(initial_state)

            last_message = final_state["messages"][-1]
            return {
                "success": True,
                "message": last_message.content if hasattr(last_message, "content") else str(last_message),
            }

        except asyncio.CancelledError:
            logger.info("ChapterAgent cancelled (client disconnected)")
            return {"success": False, "error": "cancelled"}

        except Exception as e:
            logger.error(f"ChapterAgent error: {e}")
            return {
                "success": False,
                "error": str(e),
            }


# 单例
chapter_agent = ChapterAgent()
