"""OutlineAgent — 基于 LangGraph StateGraph + Tool-Calling 的大纲子 Agent

改造自原来的方法级封装，现在 LLM 自主选择工具完成大纲创建/编辑。
支持 auto_mode：
- 默认模式（auto_mode=False）：LLM 只做 dry_run，不 commit，返回 diff 信息
- 自动模式（auto_mode=True）：LLM 可自行 commit_or_rollback
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

from app.services.supervisor.outline_tools import build_outline_tools
from app.services.supervisor.sub_agent_base import (
    chunk_to_ai_message,
    get_llm,
)

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"


class OutlineState(MessagesState):
    """OutlineAgent 的状态"""
    work_id: str
    user_message: str


def _build_outline_system_prompt(work_id: str, user_message: str, *, auto_mode: bool = False) -> str:
    if auto_mode:
        template = (PROMPT_DIR / "outline_agent_system_auto.txt").read_text(encoding="utf-8")
    else:
        template = (PROMPT_DIR / "outline_agent_system.txt").read_text(encoding="utf-8")
    return template.format(work_id=work_id or "（新建作品）", user_message=user_message)


class OutlineAgent:
    """大纲 Agent — 使用 LangGraph StateGraph 编排"""

    def __init__(self, emit: Callable):
        self.emit = emit

    def _build_graph(self, *, auto_mode: bool = False):
        tools = build_outline_tools(auto_mode=auto_mode)
        llm = get_llm(temperature=0.7, model_name="deepseek-v4-flash")  #deepseek-v4-pro 模型
        llm_with_tools = llm.bind_tools(tools)

        async def outline_agent_node(state: OutlineState) -> dict:
            messages = state.get("messages", [])

            has_system = any(isinstance(m, SystemMessage) for m in messages)
            if not has_system:
                system_prompt = _build_outline_system_prompt(
                    work_id=state.get("work_id", ""),
                    user_message=state.get("user_message", ""),
                    auto_mode=auto_mode,
                )
                full_messages = [SystemMessage(content=system_prompt)] + messages
            else:
                full_messages = messages

            aggregated = None
            async for chunk in llm_with_tools.astream(full_messages):
                aggregated = chunk if aggregated is None else aggregated + chunk

            if aggregated is None:
                raise RuntimeError("OutlineAgent LLM 未返回任何流式分片")

            response = chunk_to_ai_message(aggregated)
            return {"messages": [response]}

        def should_continue(state: OutlineState) -> str:
            messages = state.get("messages", [])
            if not messages:
                return END
            last_message = messages[-1]
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tools"
            return END

        graph = StateGraph(OutlineState)
        graph.add_node("agent", outline_agent_node)
        graph.add_node("tools", ToolNode(tools))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")
        return graph.compile()

    async def create_outline(self, idea: str, tags: list[str], db: Session,
                             db_lock: object = None) -> dict:
        """创建新大纲 — 通过 Tool-Calling 让 LLM 自主调用 generate_outline"""

        graph = self._build_graph(auto_mode=True)
        configurable = {"db": db, "emit": self.emit, "auto_mode": True}
        if db_lock is not None:
            configurable["db_lock"] = db_lock
        config = {"configurable": configurable, "recursion_limit": 25}

        system_prompt = _build_outline_system_prompt(work_id="", user_message=idea, auto_mode=True)

        initial_state = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"请根据以下创意创建一个完整的大纲：{idea}"),
            ],
            "work_id": "",
            "user_message": idea,
        }

        result = {"work_id": None, "title": None}

        def on_tool_result(event_data):
            content = event_data.get("content", "")
            if "大纲创建成功" in content:
                import re
                wid_match = re.search(r"work_id:\s*(\S+)", content)
                title_match = re.search(r"作品「(.+?)」", content)
                if wid_match:
                    result["work_id"] = wid_match.group(1).rstrip("）")
                if title_match:
                    result["title"] = title_match.group(1)

        final_state = None
        stop_after_create = False
        async for event in graph.astream(initial_state, config=config):
            for node_name, node_output in event.items():
                if node_name == "tools":
                    tool_msgs = node_output.get("messages", [])
                    for tm in tool_msgs:
                        on_tool_result({"content": str(tm.content if hasattr(tm, "content") else tm)[:500]})
                        if result.get("work_id"):
                            stop_after_create = True
                            logger.info(
                                "outline_agent.create_outline stop_after_generate work_id=%s title=%s",
                                result.get("work_id"),
                                result.get("title"),
                            )
            final_state = node_output
            if stop_after_create:
                break

        if not result.get("work_id"):
            result["error"] = "大纲生成未完成"

        return result

    async def edit_outline(self, work_id: str, message: str, history: list[dict], db: Session,
                           old_outline: dict | None = None, old_characters: list[dict] | None = None,
                           *, auto_mode: bool = False, db_lock: object = None) -> dict:
        """编辑已有大纲

        默认模式（auto_mode=False）：LLM 只做 dry_run，不 commit，返回 diff 信息。
        自动模式（auto_mode=True）：LLM 可自行调用 commit_or_rollback。
        """

        graph = self._build_graph(auto_mode=auto_mode)
        configurable = {"db": db, "emit": self.emit, "auto_mode": auto_mode}
        if db_lock is not None:
            configurable["db_lock"] = db_lock
        config = {"configurable": configurable, "recursion_limit": 25}

        system_prompt = _build_outline_system_prompt(
            work_id=work_id, user_message=message, auto_mode=auto_mode,
        )

        initial_state = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"请编辑作品 {work_id} 的大纲：{message}"),
            ],
            "work_id": work_id,
            "user_message": message,
        }

        # 收集 emit 出来的 diff 信息
        collected_diffs = {"outline_summary": {}, "character_summary": {}, "operations": []}

        original_emit = self.emit

        def capturing_emit(event: str, data: dict):
            if event == "outline_edit_diff":
                collected_diffs["outline_summary"] = data.get("summary", {})
                collected_diffs["operations"] = data.get("operations", [])
                # 自动模式：不向前端转发需确认的 diff 卡片事件
                if auto_mode:
                    return
            if event == "character_edit_diff":
                collected_diffs["character_summary"] = data.get("summary", {})
                # 自动模式：不向前端转发需确认的 diff 卡片事件
                if auto_mode:
                    return
            original_emit(event, data)

        self.emit = capturing_emit

        final_state = None
        try:
            async for event in graph.astream(initial_state, config=config):
                for node_name, node_output in event.items():
                    if node_name == "tools":
                        tool_msgs = node_output.get("messages", [])
                        for tm in tool_msgs:
                            content = tm.content if hasattr(tm, "content") else str(tm)
                            self.emit("tool_result", {"content": str(content)[:500]})
                final_state = node_output

            if auto_mode:
                return {"message": "大纲编辑已完成。"}
            else:
                return {
                    "message": "大纲变更已暂存，等待用户确认。",
                    "outline_summary": collected_diffs["outline_summary"],
                    "character_summary": collected_diffs["character_summary"],
                    "operations": collected_diffs["operations"],
                }
        except Exception as exc:
            db.rollback()
            self.emit("error", {"message": f"大纲编辑失败: {exc}"})
            return {"message": f"大纲编辑失败: {exc}", "operations": [], "error": str(exc)}
        finally:
            self.emit = original_emit

    @staticmethod
    def commit_outline_edit(work_id: str, db: Session) -> dict:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            return {"status": "error", "error": str(exc)}
        return {"status": "accepted"}

    @staticmethod
    def rollback_outline_edit(work_id: str, db: Session) -> dict:
        db.rollback()
        return {"status": "rejected"}
