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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from app.core.deepseek_llm import DeepSeekChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.agent_model import SupervisorSession
from app.services import message_service
from app.services.message_langchain import db_messages_to_langchain
from app.services.supervisor.state import SupervisorState
from app.services.supervisor.tool_registry import build_supervisor_tools
from app.services.supervisor.prompt_builder import build_supervisor_system_prompt
from app.services.supervisor.sub_agent_base import (
    chunk_to_ai_message as _chunk_to_ai_message,
    emit_llm_stream_deltas,
    stream_text_delta as _supervisor_stream_text_delta,
)
from app.services.stream_trace import gap_log

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"


def _utcnow():
    return datetime.now(timezone.utc)


from app.services.supervisor.sub_agent_base import AGENT_THINKING_EXTRA_BODY

SUPERVISOR_THINKING_EXTRA_BODY = AGENT_THINKING_EXTRA_BODY


def _build_system_message(
    work_id: str | None,
    db: Session,
    *,
    enable_todolist: bool,
    enable_evaluation: bool,
) -> SystemMessage:
    """构建 system prompt，注入作品上下文与 feature flags。"""
    work_context = "（未绑定作品）"
    requirements_doc = "（暂无需求记录）"
    if work_id:
        from app.models.work_model import Character, Work

        work = db.query(Work).filter_by(id=work_id).first()
        if work:
            parts = [f"标题: {work.title}"]
            outline = work.outline_tree or {}
            story = outline.get("story", {})
            if story.get("genre"):
                parts.append(f"类型: {story['genre']}")
            if story.get("volume"):
                parts.append(f"卷: {story['volume']}")

            characters = db.query(Character).filter_by(work_id=work_id).order_by(Character.first_appearance_stage).all()
            if characters:
                char_summary = []
                for c in characters:
                    char_summary.append(f"- {c.name}（{c.role_type}，{c.gender}，{c.age}）")
                parts.append("角色: " + "、".join(char_summary))

            macro_phases = outline.get("outline", {}).get("macro_phases", [])
            if macro_phases:
                parts.append(f"宏观阶段数: {len(macro_phases)}")

            meso_stages = outline.get("meso", {}).get("meso_stages", [])
            chapters_count = len(meso_stages) or len(macro_phases)
            parts.append(f"预计总章节数: {chapters_count}")

            work_context = "\n".join(parts)

            if work.requirements_doc:
                requirements_doc = work.requirements_doc
        else:
            work_context = "（当前绑定作品不存在）"

    content = build_supervisor_system_prompt(
        enable_todolist=enable_todolist,
        enable_evaluation=enable_evaluation,
        work_context=work_context,
        requirements_doc=requirements_doc,
    )
    return SystemMessage(content=content)


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

    def __init__(
        self,
        emit: Callable,
        db: Session,
        work_id: str | None = None,
        user_id: str | None = None,
        *,
        gap_trace_t0: float | None = None,
    ):
        self.emit = emit
        self.db = db
        self.work_id = work_id
        self.user_id = user_id
        self.gap_trace_t0 = gap_trace_t0
        self._graph = None

    def _build_graph(self, *, enable_todolist: bool, enable_evaluation: bool) -> StateGraph:
        """构建 LangGraph StateGraph"""
        model_conf = settings.get_model_config()
        llm = DeepSeekChatOpenAI(
            model=settings.default_model,
            api_key=model_conf["api_key"],
            base_url=model_conf["base_url"],
            temperature=0.7,
            streaming=True,
            max_retries=0,
        )
        if settings.fallback_model:
            from app.core.deepseek_llm import FallbackLLM
            fb_conf = settings.get_model_config(settings.fallback_model)
            fallback = DeepSeekChatOpenAI(
                model=settings.fallback_model,
                api_key=fb_conf["api_key"],
                base_url=fb_conf["base_url"],
                temperature=0.7,
                streaming=True,
                max_retries=0,
            )
            llm = FallbackLLM(llm, fallback)
        tools = build_supervisor_tools(
            enable_todolist=enable_todolist,
            enable_evaluation=enable_evaluation,
        )
        llm_with_tools = llm.bind_tools(tools, extra_body=SUPERVISOR_THINKING_EXTRA_BODY)

        tool_node = ToolNode(tools)

        async def agent_node(state: SupervisorState) -> dict:
            """LLM 节点：接收 messages，流式输出正文到 SSE，并返回完整 AIMessage。"""
            messages = state.get("messages", [])
            system_msg = _build_system_message(
                state.get("work_id"),
                self.db,
                enable_todolist=enable_todolist,
                enable_evaluation=enable_evaluation,
            )

            full_messages = [system_msg] + messages

            self.emit("stage_start", {"stage": "thinking", "label": "AI 思考中"})

            session_id = state.get("session_id")
            gap_log(
                "agent_llm_astream_begin",
                session_id=session_id,
                t0=self.gap_trace_t0,
                input_messages=len(full_messages),
            )

            # 记录输入上下文规模
            _log_msg_summary = []
            for i, m in enumerate(full_messages):
                role = getattr(m, "type", type(m).__name__)
                content_len = len(getattr(m, "content", "") or "")
                tc_count = len(getattr(m, "tool_calls", []) or [])
                _log_msg_summary.append(f"[{i}]{role}:content_len={content_len},tool_calls={tc_count}")
            logger.info(
                "supervisor.agent_node input_messages=%d total_input_len=%d msg_summary=[%s]",
                len(full_messages),
                sum(len(getattr(m, "content", "") or "") for m in full_messages),
                " | ".join(_log_msg_summary),
            )

            aggregated: AIMessageChunk | None = None
            chunk_count = 0
            text_chunk_count = 0
            tool_chunk_count = 0
            first_chunk_logged = False
            t_stream = time.perf_counter()
            async for chunk in llm_with_tools.astream(full_messages):
                if not first_chunk_logged:
                    first_chunk_logged = True
                    gap_log(
                        "agent_llm_first_chunk",
                        session_id=session_id,
                        t0=self.gap_trace_t0,
                    )
                aggregated = chunk if aggregated is None else aggregated + chunk
                chunk_count += 1
                emit_llm_stream_deltas(self.emit, "supervisor_stream", chunk)
                if _supervisor_stream_text_delta(chunk):
                    text_chunk_count += 1
                # 检测 tool_call 分片
                if getattr(chunk, "tool_call_chunks", None):
                    tool_chunk_count += 1
                # 每50个chunk采样一次，记录原始chunk内容
                if chunk_count <= 3 or chunk_count % 50 == 0:
                    chunk_content = getattr(chunk, "content", "")
                    chunk_tc = getattr(chunk, "tool_call_chunks", None)
                    logger.debug(
                        "supervisor.agent_node chunk#%d content=%s tool_call_chunks=%s",
                        chunk_count,
                        repr(chunk_content) if chunk_content else "(empty)",
                        repr(chunk_tc) if chunk_tc else "(none)",
                    )

            stream_elapsed_ms = (time.perf_counter() - t_stream) * 1000

            # 记录流式输出摘要
            if aggregated is None:
                logger.error(
                    "supervisor.agent_node stream_returned_empty chunk_count=0 elapsed_ms=%.1f",
                    stream_elapsed_ms,
                )
            else:
                agg_content_len = len(getattr(aggregated, "content", "") or "")
                agg_tc = len(getattr(aggregated, "tool_calls", []) or [])
                logger.info(
                    "supervisor.agent_node stream_done chunks=%d text_chunks=%d tool_chunks=%d "
                    "agg_content_len=%d agg_tool_calls=%d elapsed_ms=%.1f",
                    chunk_count, text_chunk_count, tool_chunk_count,
                    agg_content_len, agg_tc, stream_elapsed_ms,
                )
                # 记录聚合内容预览（前500字）用于排查空输出
                if agg_content_len == 0 and agg_tc == 0:
                    logger.warning(
                        "supervisor.agent_node empty_output aggregated_repr=%s",
                        repr(aggregated),
                    )

            if aggregated is None:
                raise RuntimeError("统筹 LLM 未返回任何流式分片")

            response = _chunk_to_ai_message(aggregated)

            tool_names = []
            if hasattr(response, "tool_calls") and response.tool_calls:
                tool_names = [tc.get("name", "") for tc in response.tool_calls]

            return {"messages": [response], "current_tool": ", ".join(tool_names)}

        graph = StateGraph(SupervisorState)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", tool_node)

        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")

        return graph.compile()

    async def start(
        self,
        message: str,
        *,
        auto_mode: bool = True,
        enable_todolist: bool = False,
        enable_evaluation: bool = False,
    ) -> dict:
        """启动新会话"""
        t0 = time.perf_counter()

        # 会话和首条 user 消息必须原子落库，避免出现“空 session”残留。
        session = SupervisorSession(
            work_id=self.work_id,
            user_id=self.user_id,
            stage="running",
            status="running",
            auto_mode=auto_mode,
            enable_todolist=enable_todolist,
            enable_evaluation=enable_evaluation,
        )
        self.db.add(session)
        self.db.flush()

        logger.info("supervisor.start session_id=%s work_id=%s", session.id, self.work_id)

        # 用户消息写入 messages 表（不单独提交，与 session 一起提交）
        message_service.create_message(
            self.db,
            session_id=session.id,
            role="user",
            content=message,
            work_id=self.work_id,
            sort_order=0,
            commit=False,
        )
        try:
            self.db.commit()
            self.db.refresh(session)
        except Exception:
            self.db.rollback()
            raise

        self.emit("session_created", {"session_id": session.id})
        gap_log("session_created", session_id=session.id, t0=self.gap_trace_t0)

        result = await self._run_graph(session, message)

        logger.info(
            "supervisor.start done session_id=%s elapsed_ms=%.1f",
            session.id, (time.perf_counter() - t0) * 1000,
        )
        return result

    async def resume(
        self,
        session_id: str,
        message: str,
        *,
        enable_todolist: bool | None = None,
        enable_evaluation: bool | None = None,
    ) -> dict:
        """继续已有会话"""
        session = self.db.query(SupervisorSession).filter_by(id=session_id).first()
        if not session:
            self.emit("error", {"message": f"会话 {session_id} 不存在"})
            return {"error": "会话不存在"}

        if enable_todolist is not None:
            session.enable_todolist = enable_todolist
        if enable_evaluation is not None:
            session.enable_evaluation = enable_evaluation

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
        session.interrupted = False
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        if session.work_id:
            self.work_id = session.work_id

        gap_log(
            "resume_graph_begin",
            session_id=session.id,
            t0=self.gap_trace_t0,
            message_len=len(message or ""),
        )

        result = await self._run_graph(session, message)

        return result

    async def _run_graph(self, session: SupervisorSession, user_message: str) -> dict:
        """执行 LangGraph StateGraph"""
        import threading

        config = {
            "configurable": {
                "db": self.db,
                "db_lock": threading.Lock(),
                "emit": self.emit,
                "supervisor_session_id": session.id,
                "gap_trace_t0": self.gap_trace_t0,
                "work_id": session.work_id or self.work_id or "",
                "auto_mode": session.auto_mode,
                "enable_todolist": session.enable_todolist,
                "enable_evaluation": session.enable_evaluation,
                "enable_child_todolist": session.enable_todolist,
                "user_id": session.user_id or self.user_id,
                "sub_agent_memories": {},
            },
            "recursion_limit": 100,
        }

        db_messages = message_service.get_messages_by_session(self.db, session.id)
        langchain_messages = db_messages_to_langchain(db_messages)
        gap_log(
            "run_graph_begin",
            session_id=session.id,
            t0=self.gap_trace_t0,
            history_messages=len(langchain_messages),
        )

        initial_state = {
            "messages": langchain_messages,
            "work_id": self.work_id or "",
            "session_id": session.id,
            "current_tool": "",
            "tool_results": [],
        }

        try:
            graph = self._build_graph(
                enable_todolist=session.enable_todolist,
                enable_evaluation=session.enable_evaluation,
            )

            # 流式执行
            final_state = None
            pending_stop = False  # 标记：tools 节点触发了 waiting，等 agent 再跑一轮后退出
            try:
                async for event in graph.astream(initial_state, config=config):
                    # event 是 dict: {node_name: node_output}
                    for node_name, node_output in event.items():
                        gap_log(
                            "graph_node_done",
                            session_id=session.id,
                            t0=self.gap_trace_t0,
                            node=node_name,
                        )
                        self._process_graph_event(node_name, node_output)

                        if node_name == "tools":
                            tool_msgs = node_output.get("messages", [])
                            for tm in tool_msgs:
                                content = tm.content if hasattr(tm, "content") else str(tm)
                                self.emit("tool_result", {"content": str(content)})

                            # tools 执行后检查是否需要等待用户
                            self.db.flush()
                            if session.status == "waiting" and session.active_child:
                                pending_stop = True
                                logger.info(
                                    "supervisor._run_graph wait_for_user session_id=%s status=%s stage=%s active_child=%s",
                                    session.id,
                                    session.status,
                                    session.stage,
                                    bool(session.active_child),
                                )

                    final_state = node_output

                    # 中断检查：每个节点完成后检查是否被用户标记中断
                    self.db.refresh(session)
                    if session.interrupted:
                        logger.info("supervisor._run_graph interrupted session_id=%s", session.id)
                        session.status = "interrupted"
                        session.stage = "done"
                        self.db.flush()
                        self.emit("supervisor_interrupted", {"message": "任务已被用户中断"})
                        break

                    # 只在 agent 节点后退出，确保 Supervisor 生成最终回复
                    if pending_stop and node_name == "agent":
                        break
            except GeneratorExit:
                logger.info(
                    "supervisor._run_graph GeneratorExit session_id=%s (client disconnected)",
                    session.id,
                )

            # 提取最终 AI 回复
            final_messages = final_state.get("messages", []) if final_state else []
            assistant_content = ""
            assistant_reasoning = ""
            for msg in reversed(final_messages):
                if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                    assistant_content = msg.content
                    assistant_reasoning = (
                        getattr(msg, "additional_kwargs", {}).get("reasoning_content") or ""
                    )
                    break

            if not assistant_content and final_messages:
                last = final_messages[-1]
                if isinstance(last, AIMessage):
                    assistant_content = last.content or ""

            # 中断时跳过正常完成逻辑，直接返回
            if session.interrupted:
                logger.info("supervisor._run_graph returning_interrupted_state session_id=%s", session.id)
                self.emit("supervisor_done", {"message": "（任务已被中断）"})
                return {"message": "（任务已被中断）"}

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
            final_meta: dict[str, Any] = {"tool_calls": tool_history}
            if assistant_reasoning:
                final_meta["reasoning_content"] = assistant_reasoning
            message_service.create_message(
                self.db,
                session_id=session.id,
                role="assistant",
                content=assistant_content,
                work_id=self.work_id,
                sort_order=next_order,
                meta=final_meta,
            )

            # edit_chapter 工具内已将 status 置为 waiting 并写入 active_child，此处不得覆盖为 completed
            if session.status == "waiting" and session.active_child:
                session.stage = "executing"
            else:
                session.stage = "done"
                session.status = "completed"
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise

            self.emit("supervisor_done", {"message": assistant_content})

            return {"message": assistant_content}

        except Exception as exc:
            logger.exception("supervisor._run_graph failed: %s", exc)
            self.db.rollback()
            self.emit("error", {"message": str(exc)})
            session.status = "error"
            session.stage = "done"
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
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
                    save_meta: dict[str, Any] = {"phase": "intermediate"}
                    rc = getattr(msg, "additional_kwargs", {}).get("reasoning_content")
                    if rc:
                        save_meta["reasoning_content"] = rc
                    message_service.create_message(
                        db,
                        session_id=session.id,
                        role="assistant",
                        content=content,
                        work_id=self.work_id,
                        sort_order=next_order,
                        meta=save_meta,
                    )
                    next_order += 1

            if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
                rc = getattr(msg, "additional_kwargs", {}).get("reasoning_content")
                for i, tc in enumerate(msg.tool_calls):
                    tc_meta: dict[str, Any] = {"args": tc.get("args", {})}
                    tc_id = tc.get("id")
                    if tc_id:
                        tc_meta["tool_call_id"] = tc_id
                    if i == 0 and rc:
                        tc_meta["reasoning_content"] = rc
                    message_service.create_message(
                        db,
                        session_id=session.id,
                        role="tool_call",
                        content=tc.get("name", ""),
                        work_id=self.work_id,
                        sort_order=next_order,
                        meta=tc_meta,
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
                    content=str(content),
                    work_id=self.work_id,
                    sort_order=next_order,
                    meta={
                        "tool_name": getattr(msg, "name", "unknown"),
                        "tool_call_id": getattr(msg, "tool_call_id", "") or "",
                    },
                )
                next_order += 1

    def _process_graph_event(self, node_name: str, node_output: dict) -> None:
        """处理 StateGraph 节点输出，发射 SSE 事件"""
        if node_name == "tools":
            messages = node_output.get("messages", [])
            for msg in messages:
                tool_name = getattr(msg, "name", "unknown")
                content_preview = str(getattr(msg, "content", ""))
                logger.info(
                    "supervisor.tool_result tool=%s content_preview=%s",
                    tool_name, content_preview,
                )
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
