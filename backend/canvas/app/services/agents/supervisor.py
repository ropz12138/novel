"""Supervisor Agent - 主编排Agent"""
import json
import logging
import asyncio
from pathlib import Path
from typing import Callable, Optional, Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.tools import tool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langsmith import traceable

from app.services.agents.llm import get_llm, bind_tools_to_llm, should_continue


logger = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).parent / "prompts"


def _get_db():
    from app.database import SessionLocal
    return SessionLocal()


def get_canvas_overview_str(work_id: str = None):
    """获取画布概览字符串"""
    from app.services.agents.tools.query_tools import get_canvas_overview
    if work_id:
        return get_canvas_overview.invoke({"work_id": work_id})
    return get_canvas_overview.invoke({})


# 全局context存储（简单实现）
_current_context: Dict[str, Any] = {}


def set_context(context: Dict[str, Any]):
    """设置当前上下文"""
    global _current_context
    _current_context = context


def get_context() -> Dict[str, Any]:
    """获取当前上下文"""
    return _current_context


class SupervisorState(MessagesState):
    """Supervisor状态"""
    user_message: str = ""
    canvas_overview: str = ""


class SupervisorAgent:
    """Supervisor Agent - 主编排Agent"""

    def __init__(self, emit: Optional[Callable] = None):
        self.emit = emit

    def _build_system_prompt(self, user_message: str, canvas_overview: str) -> str:
        """构建系统提示"""
        template_path = PROMPT_DIR / "supervisor_system.txt"
        template = template_path.read_text(encoding="utf-8")
        return template.format(
            canvas_overview=canvas_overview,
            user_message=user_message,
        )

    def _get_tools(self):
        """单 Agent：直接挂全部操作工具，不再 dispatch 到子 agent。"""
        from app.services.agents.tools.query_tools import query_tools
        from app.services.agents.tools.node_tools import node_tools
        from app.services.agents.tools.chapter_tools import write_chapter
        from app.services.agents.tools.canvas_evaluate import evaluate_layout_tool

        return query_tools + node_tools + [write_chapter, evaluate_layout_tool]

    def _build_graph(self):
        """构建LangGraph"""
        tools = self._get_tools()
        tool_node = ToolNode(tools)

        llm = get_llm(temperature=0.5)
        llm_with_tools = bind_tools_to_llm(llm, tools)

        async def agent_node(state: SupervisorState):
            """Agent节点 - 流式输出"""
            messages = state["messages"]

            # 使用 astream 逐 token 推送
            aggregated = None
            async for chunk in llm_with_tools.astream(messages):
                if self.emit:
                    content = getattr(chunk, "content", "") or ""
                    if content:
                        await self.emit("supervisor_stream", {
                            "chunk": content,
                            "phase": "content",
                        })
                    reasoning = getattr(chunk, "additional_kwargs", {}).get("reasoning_content", "")
                    if reasoning:
                        await self.emit("supervisor_stream", {
                            "chunk": reasoning,
                            "phase": "reasoning",
                        })
                aggregated = chunk if aggregated is None else aggregated + chunk

            if aggregated is None:
                raise RuntimeError("LLM 未返回任何响应")

            from langchain_core.messages import AIMessageChunk
            if isinstance(aggregated, AIMessageChunk):
                response = AIMessage(
                    content=aggregated.content or "",
                    tool_calls=list(aggregated.tool_calls) if aggregated.tool_calls else [],
                )
            else:
                response = aggregated

            # 工具调用通知
            if self.emit and hasattr(response, "tool_calls") and response.tool_calls:
                tool_names = [tc.get("name", "") for tc in response.tool_calls]
                await self.emit("tool_calls", {"tools": tool_names})

            return {"messages": [response]}

        graph = StateGraph(SupervisorState)
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

    @traceable(
        name="canvas_supervisor.run",
        run_type="chain",
        metadata={"component": "canvas_supervisor"},
    )
    async def run(self, user_message: str, context: Dict[str, Any] = None, emit: Optional[Callable] = None) -> dict:
        """运行Supervisor Agent"""
        try:
            if context:
                set_context(context)

            self.emit = emit

            work_id = context.get("work_id") if context else None
            canvas_overview = get_canvas_overview_str(work_id)

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

            # 使用 astream_events 流式执行，只捕获 supervisor 自己的 agent_node 事件
            final_state = None
            agent_node_name = "agent"  # supervisor graph 中的 agent 节点名
            async for event in graph.astream_events(initial_state, version="v2"):
                kind = event.get("event", "")
                event_name = event.get("name", "")
                
                # 只处理 supervisor 自己的 agent 节点的 LLM 流式事件
                if kind == "on_chat_model_stream" and event_name == agent_node_name:
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and self.emit:
                        content = getattr(chunk, "content", "") or ""
                        if content:
                            await self.emit("supervisor_stream", {"chunk": content, "phase": "content"})
                        reasoning = getattr(chunk, "additional_kwargs", {}).get("reasoning_content", "")
                        if reasoning:
                            await self.emit("supervisor_stream", {"chunk": reasoning, "phase": "reasoning"})
                elif kind == "on_tool_start" and event.get("parent_run_id") is None:
                    # 只处理顶层工具调用
                    if self.emit:
                        tool_name = event.get("name", "unknown")
                        await self.emit("stage_start", {"stage": "tool", "label": f"调用工具: {tool_name}"})
                elif kind == "on_tool_end" and event.get("parent_run_id") is None:
                    # 只处理顶层工具结果
                    if self.emit:
                        tool_name = event.get("name", "unknown")
                        await self.emit("tool_executed", {"tool": tool_name})
                elif kind == "on_chain_end" and event.get("name") == agent_node_name:
                    output = event.get("data", {}).get("output")
                    if output and isinstance(output, dict):
                        final_state = output
                await asyncio.sleep(0)

            if final_state is None:
                final_state = await graph.ainvoke(initial_state, config={"recursion_limit": 50})
                last_message = final_state["messages"][-1]
            else:
                messages = final_state.get("messages", [])
                last_message = messages[-1] if messages else None
            result = {
                "success": True,
                "message": last_message.content if hasattr(last_message, "content") else str(last_message),
            }

            if emit:
                await emit("supervisor_done", {"message": result["message"]})

            return result

        except Exception as e:
            logger.error(f"SupervisorAgent error: {e}")
            return {
                "success": False,
                "error": str(e),
            }


# 单例
supervisor_agent = SupervisorAgent()
