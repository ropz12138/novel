"""统筹 Agent — LangGraph StateGraph + Tool-Calling 架构

职责:
1. 接收用户消息
2. LLM 自主决定调用哪些工具（不再有独立的意图分类步骤）
3. 通过 LangGraph StateGraph 管理 agent_node ↔ tool_node 的循环
4. 聚合工具执行的 SSE 事件，统一输出给前端
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_model import SupervisorSession
from app.services import message_service
from app.services.supervisor.state import SupervisorState
from app.services.supervisor.tools import ALL_TOOLS

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def _utcnow():
    return datetime.now(timezone.utc)


def _supervisor_stream_text_delta(chunk: AIMessageChunk) -> str:
    """从 LLM 流式 chunk 取出应对用户展示的正文增量；不展示纯 tool-call 分片。"""
    if chunk is None:
        return ""
    # 仅有 tool 分片、无正文时跳过（避免把 arguments JSON 当正文刷给前端）
    if getattr(chunk, "tool_call_chunks", None) and not (getattr(chunk, "content", None) or ""):
        return ""
    c = getattr(chunk, "content", None)
    if c is None or c == "":
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for part in c:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text") or ""))
                # 忽略 tool_call / refusal 等块，避免 JSON 泄漏到聊天区
            elif hasattr(part, "text"):
                parts.append(str(getattr(part, "text", "") or ""))
        return "".join(parts)
    return str(c)


def _chunk_to_ai_message(full: AIMessageChunk | AIMessage) -> AIMessage:
    """将累计的 AIMessageChunk 转为 AIMessage，供 LangGraph 状态与 tool 路由使用。"""
    if isinstance(full, AIMessage):
        return full
    tc = list(full.tool_calls) if getattr(full, "tool_calls", None) else []
    kwargs: dict[str, Any] = {"content": full.content or "", "tool_calls": tc}
    _id = getattr(full, "id", None)
    if _id:
        kwargs["id"] = _id
    return AIMessage(**kwargs)


def _build_system_message(work_id: str | None, db: Session) -> SystemMessage:
    """构建 system prompt，注入作品上下文"""
    template = (PROMPT_DIR / "system.txt").read_text(encoding="utf-8")

    work_context = "（未绑定作品）"
    if work_id:
        from app.models.work_model import Character, Work

        work = db.query(Work).filter_by(id=work_id).first()
        if work:
            parts = [f"作品ID: {work_id}", f"标题: {work.title}"]
            outline = work.outline_tree or {}
            story = outline.get("story", {})
            if story.get("genre"):
                parts.append(f"类型: {story['genre']}")
            if story.get("volume"):
                parts.append(f"卷: {story['volume']}")

            characters = db.query(Character).filter_by(work_id=work_id).order_by(Character.first_chapter).all()
            if characters:
                char_summary = []
                for c in characters:
                    char_summary.append(f"- {c.name}（{c.role_type}，{c.gender}，{c.age}）")
                parts.append("角色: " + "、".join(char_summary))

            timeline = outline.get("timeline", [])
            if timeline:
                parts.append(f"大纲时间线节点数: {len(timeline)}")

            chapters_count = len(outline.get("timeline", []))
            parts.append(f"预计总章节数: {chapters_count}")

            work_context = "\n".join(parts)
        else:
            work_context = f"（作品 {work_id} 不存在）"

    return SystemMessage(content=template.format(work_context=work_context))


def _should_continue(state: SupervisorState) -> str:
    """条件边：判断 LLM 是否还在调用工具"""
    messages = state.get("messages", [])
    if not messages:
        return END
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


class SupervisorAgent:
    """统筹 Agent — 使用 LangGraph StateGraph 编排 LLM 和工具调用"""

    def __init__(self, emit: Callable, db: Session, work_id: str | None = None):
        self.emit = emit
        self.db = db
        self.work_id = work_id
        self._graph = None

    def _build_graph(self) -> StateGraph:
        """构建 LangGraph StateGraph"""
        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.7,
            streaming=True,
        )
        llm_with_tools = llm.bind_tools(ALL_TOOLS)

        tool_node = ToolNode(ALL_TOOLS)

        async def agent_node(state: SupervisorState) -> dict:
            """LLM 节点：接收 messages，流式输出正文到 SSE，并返回完整 AIMessage。"""
            messages = state.get("messages", [])
            system_msg = _build_system_message(state.get("work_id"), self.db)

            full_messages = [system_msg] + messages

            self.emit("stage_start", {"stage": "thinking", "label": "AI 思考中"})

            aggregated: AIMessageChunk | None = None
            async for chunk in llm_with_tools.astream(full_messages):
                aggregated = chunk if aggregated is None else aggregated + chunk
                delta = _supervisor_stream_text_delta(chunk)
                if delta:
                    self.emit("supervisor_stream", {"chunk": delta})

            if aggregated is None:
                raise RuntimeError("统筹 LLM 未返回任何流式分片")

            response = _chunk_to_ai_message(aggregated)

            tool_names = []
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_names = [tc.get("name", "") for tc in response.tool_calls]
                self.emit("tool_calls", {
                    "tools": tool_names,
                })

            return {"messages": [response], "current_tool": ", ".join(tool_names)}

        graph = StateGraph(SupervisorState)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", tool_node)

        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")

        return graph.compile()

    async def start(self, message: str) -> dict:
        """启动新会话"""
        t0 = time.perf_counter()

        session = SupervisorSession(
            work_id=self.work_id,
            stage="running",
            status="running",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        logger.info("supervisor.start session_id=%s work_id=%s", session.id, self.work_id)
        self.emit("session_created", {"session_id": session.id})

        # 用户消息写入 messages 表
        message_service.create_message(
            self.db,
            session_id=session.id,
            role="user",
            content=message,
            work_id=self.work_id,
            sort_order=0,
        )

        result = await self._run_graph(session, message)

        logger.info(
            "supervisor.start done session_id=%s elapsed_ms=%.1f",
            session.id, (time.perf_counter() - t0) * 1000,
        )
        return result

    async def resume(self, session_id: str, message: str) -> dict:
        """继续已有会话"""
        session = self.db.query(SupervisorSession).filter_by(id=session_id).first()
        if not session:
            self.emit("error", {"message": f"会话 {session_id} 不存在"})
            return {"error": "会话不存在"}

        # 用户消息写入 messages 表
        next_order = message_service.get_next_sort_order(self.db, session_id)
        message_service.create_message(
            self.db,
            session_id=session_id,
            role="user",
            content=message,
            work_id=session.work_id,
            sort_order=next_order,
        )

        session.status = "running"
        session.stage = "running"
        self.db.commit()

        if session.work_id:
            self.work_id = session.work_id

        result = await self._run_graph(session, message)

        return result

    async def _run_graph(self, session: SupervisorSession, user_message: str) -> dict:
        """执行 LangGraph StateGraph"""
        config = {
            "configurable": {
                "db": self.db,
                "emit": self.emit,
                "supervisor_session_id": session.id,
            },
            "recursion_limit": 25,
        }

        # 从 messages 表构建历史 LangChain messages
        db_messages = message_service.get_messages_by_session(self.db, session.id)
        langchain_messages = []
        for m in db_messages:
            if m.role == "user":
                langchain_messages.append(HumanMessage(content=m.content))
            elif m.role == "assistant":
                langchain_messages.append(AIMessage(content=m.content))

        initial_state = {
            "messages": langchain_messages,
            "work_id": self.work_id or "",
            "session_id": session.id,
            "current_tool": "",
            "tool_results": [],
        }

        try:
            graph = self._build_graph()

            # 流式执行
            final_state = None
            async for event in graph.astream(initial_state, config=config):
                # event 是 dict: {node_name: node_output}
                for node_name, node_output in event.items():
                    self._process_graph_event(node_name, node_output)

                    if node_name == "tools":
                        tool_msgs = node_output.get("messages", [])
                        for tm in tool_msgs:
                            content = tm.content if hasattr(tm, "content") else str(tm)
                            self.emit("tool_result", {"content": str(content)[:500]})

                final_state = node_output

            # 提取最终 AI 回复
            final_messages = final_state.get("messages", []) if final_state else []
            assistant_content = ""
            for msg in reversed(final_messages):
                if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                    assistant_content = msg.content
                    break

            if not assistant_content and final_messages:
                last = final_messages[-1]
                if isinstance(last, AIMessage):
                    assistant_content = last.content or ""

            # 中间过程写入 messages 表（仅持久化本轮新增切片）
            self._save_intermediate_messages(
                self.db,
                session,
                final_messages,
                history_len=len(langchain_messages),
                final_assistant_content=assistant_content,
            )

            # 最终回复写入 messages 表
            next_order = message_service.get_next_sort_order(self.db, session.id)
            tool_history = self._extract_tool_history(final_messages)
            message_service.create_message(
                self.db,
                session_id=session.id,
                role="assistant",
                content=assistant_content,
                work_id=self.work_id,
                sort_order=next_order,
                meta={"tool_calls": tool_history},
            )

            # edit_chapter 工具内已将 status 置为 waiting 并写入 active_child，此处不得覆盖为 completed
            if session.status == "waiting" and session.active_child:
                session.stage = "executing"
            else:
                session.stage = "done"
                session.status = "completed"
            self.db.commit()

            self.emit("supervisor_done", {"message": assistant_content})

            return {"message": assistant_content}

        except Exception as exc:
            logger.exception("supervisor._run_graph failed: %s", exc)
            self.emit("error", {"message": str(exc)})
            session.status = "error"
            session.stage = "done"
            self.db.commit()
            return {"error": str(exc)}

    def _save_intermediate_messages(
        self,
        db: Session,
        session: SupervisorSession,
        final_messages: list,
        history_len: int = 0,
        final_assistant_content: str = "",
    ) -> None:
        """将中间过程（tool_call / tool_result / thinking）写入 messages 表"""
        next_order = message_service.get_next_sort_order(db, session.id)
        new_messages = final_messages[history_len:] if history_len > 0 else final_messages

        for i, msg in enumerate(new_messages):
            # 中间 assistant 文本（阶段性用户可见提示）入库，刷新后可还原
            if isinstance(msg, AIMessage):
                content = (msg.content or "").strip()
                is_final_assistant = (
                    i == len(new_messages) - 1
                    and bool(content)
                    and not getattr(msg, "tool_calls", None)
                    and content == (final_assistant_content or "").strip()
                )
                if content and not is_final_assistant:
                    message_service.create_message(
                        db,
                        session_id=session.id,
                        role="assistant",
                        content=content,
                        work_id=self.work_id,
                        sort_order=next_order,
                        meta={"phase": "intermediate"},
                    )
                    next_order += 1

            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                # tool_call
                for tc in msg.tool_calls:
                    message_service.create_message(
                        db,
                        session_id=session.id,
                        role="tool_call",
                        content=tc.get("name", ""),
                        work_id=self.work_id,
                        sort_order=next_order,
                        meta={"args": tc.get("args", {})},
                    )
                    next_order += 1
            # ToolMessage (tool_result)
            from langchain_core.messages import ToolMessage
            if isinstance(msg, ToolMessage):
                content = msg.content if hasattr(msg, "content") else str(msg)
                message_service.create_message(
                    db,
                    session_id=session.id,
                    role="tool_result",
                    content=str(content)[:500],
                    work_id=self.work_id,
                    sort_order=next_order,
                    meta={"tool_name": getattr(msg, "name", "unknown")},
                )
                next_order += 1

    def _process_graph_event(self, node_name: str, node_output: dict) -> None:
        """处理 StateGraph 节点输出，发射 SSE 事件"""
        if node_name == "tools":
            messages = node_output.get("messages", [])
            for msg in messages:
                tool_name = getattr(msg, "name", "unknown")
                self.emit("tool_executed", {"tool": tool_name})
        elif node_name == "agent":
            current_tool = node_output.get("current_tool", "")
            if current_tool:
                self.emit("stage_start", {"stage": "tool_calling", "label": f"调用工具: {current_tool}"})

    def _extract_tool_history(self, messages: list) -> list[dict]:
        """从最终 messages 中提取工具调用历史"""
        tool_history = []
        for msg in messages:
            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_history.append({
                        "tool": tc.get("name", ""),
                        "args": tc.get("args", {}),
                    })
        return tool_history
