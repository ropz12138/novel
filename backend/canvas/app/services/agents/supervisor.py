"""Supervisor Agent - 主编排Agent"""
import json
import logging
import uuid
from pathlib import Path
from typing import Callable, Optional, Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langsmith import traceable

from app.services.agents.llm import get_llm, bind_tools_to_llm, should_continue
from app.services.llm_stream import chunk_to_ai_message, emit_llm_stream_deltas
from app.services.message_content_utils import extract_text_content, extract_tool_calls
from app.services.tool_result_utils import lookup_tool_results_after, tool_message_success
from app.models.user import User


logger = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).parent / "prompts"
MAX_TOOL_CALL_PARSE_RETRIES = 2
INVALID_TOOL_CALL_ARGS_LIMIT = 12000
INVALID_TOOL_CALL_CONTEXT_WINDOW = 240


def _collect_messages_from_graph_event(
    all_messages: list,
    node_name: str,
    node_output,
) -> list:
    """从 graph.astream 单条事件中累积本轮新增消息（对齐 main 分支）。"""
    if node_name == "messages" and isinstance(node_output, list):
        return list(node_output)
    if not isinstance(node_output, dict):
        return all_messages
    msgs = node_output.get("messages", [])
    if not msgs:
        return all_messages
    if node_name in ("agent", "tools"):
        return [*all_messages, *msgs]
    return all_messages


def _tool_call_diagnostic_payload(message) -> dict:
    """Summarize streaming tool-call parse state without dumping huge args."""
    invalid_tool_calls = getattr(message, "invalid_tool_calls", None) or []
    tool_call_chunks = getattr(message, "tool_call_chunks", None) or []
    response_metadata = getattr(message, "response_metadata", None) or {}

    def _summarize_call(call: dict) -> dict:
        args = call.get("args", "")
        return {
            "name": call.get("name") or "",
            "id": call.get("id") or "",
            "args_preview": str(args)[:500],
            "args_len": len(str(args)),
            "error": str(call.get("error") or "")[:300],
        }

    return {
        "finish_reason": response_metadata.get("finish_reason"),
        "tool_calls_count": len(getattr(message, "tool_calls", None) or []),
        "invalid_tool_calls_count": len(invalid_tool_calls),
        "tool_call_chunks_count": len(tool_call_chunks),
        "invalid_tool_calls": [
            _summarize_call(call)
            for call in invalid_tool_calls
            if isinstance(call, dict)
        ][:3],
        "tool_call_chunks": [
            _summarize_call(call)
            for call in tool_call_chunks
            if isinstance(call, dict)
        ][:3],
    }


def _json_error_details(raw_args: Any) -> dict:
    """Parse invalid tool args again so the model gets an actionable location."""
    if isinstance(raw_args, str):
        args_text = raw_args
    else:
        args_text = json.dumps(raw_args, ensure_ascii=False, default=str)

    try:
        json.loads(args_text)
    except json.JSONDecodeError as e:
        start = max(0, e.pos - INVALID_TOOL_CALL_CONTEXT_WINDOW)
        end = min(len(args_text), e.pos + INVALID_TOOL_CALL_CONTEXT_WINDOW)
        return {
            "valid_json": False,
            "message": e.msg,
            "line": e.lineno,
            "column": e.colno,
            "position": e.pos,
            "context": args_text[start:end],
        }
    except Exception as e:
        return {
            "valid_json": False,
            "message": str(e),
            "line": None,
            "column": None,
            "position": None,
            "context": args_text[: INVALID_TOOL_CALL_CONTEXT_WINDOW * 2],
        }

    return {
        "valid_json": True,
        "message": "",
        "line": None,
        "column": None,
        "position": None,
        "context": "",
    }


def _build_tool_call_parse_feedback(message) -> str:
    """Build a corrective prompt for malformed streaming tool-call JSON."""
    invalid_tool_calls = getattr(message, "invalid_tool_calls", None) or []
    if not invalid_tool_calls:
        tool_call_chunks = getattr(message, "tool_call_chunks", None) or []
        invalid_tool_calls = tool_call_chunks

    sections = [
        "你刚才尝试调用工具，但工具参数没有被解析成合法 JSON，因此工具没有执行。",
        "请根据下面的原始参数和错误位置，重新发起同一个工具调用。",
        "要求：只重新调用工具，不要用普通文本回答；修复 JSON 语法；尽量保持原本要创建或修改的内容不变；JSON 字符串里的英文双引号必须转义，或改用中文引号。",
    ]

    for idx, call in enumerate(invalid_tool_calls[:3], start=1):
        if not isinstance(call, dict):
            continue
        name = call.get("name") or "unknown"
        call_id = call.get("id") or ""
        raw_args = call.get("args") or ""
        args_text = raw_args if isinstance(raw_args, str) else json.dumps(raw_args, ensure_ascii=False, default=str)
        truncated = len(args_text) > INVALID_TOOL_CALL_ARGS_LIMIT
        shown_args = args_text[:INVALID_TOOL_CALL_ARGS_LIMIT]
        details = _json_error_details(args_text)

        sections.append(
            "\n".join([
                f"\n失败的工具调用 #{idx}: {name}",
                f"tool_call_id: {call_id}" if call_id else "tool_call_id: unknown",
                "JSONDecodeError:",
                f"- message: {details['message'] or call.get('error') or 'unknown'}",
                f"- line: {details['line']}",
                f"- column: {details['column']}",
                f"- position: {details['position']}",
                "错误附近内容:",
                details["context"] or "(无)",
                "原始 args:",
                shown_args + ("\n...(args truncated)" if truncated else ""),
            ])
        )

    return "\n\n".join(sections)


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

    def _build_system_prompt(self, context_node_ids: list | None = None) -> str:
        """构建系统提示"""
        template_path = PROMPT_DIR / "supervisor_system.txt"
        template = template_path.read_text(encoding="utf-8")

        # 用户指定的对话上下文节点：提示 agent 用 read_node_content 读取后参考
        context_section = ""
        if context_node_ids:
            ids_list = "\n".join(f"- {nid}" for nid in context_node_ids)
            context_section = (
                "## 用户指定的对话上下文\n"
                "用户已把以下节点标记为本对话的重点上下文，请优先用 read_node_content 读取它们的内容，作为本次对话的核心参考：\n"
                f"{ids_list}\n\n"
            )

        return template.format(context_section=context_section)

    def _get_tools(self):
        """单 Agent：直接挂全部操作工具，不再 dispatch 到子 agent。"""
        from app.services.agents.tools.query_tools import query_tools
        from app.services.agents.tools.node_tools import node_tools
        from app.services.agents.tools.chapter_tools import write_chapter, edit_chapter_content, evaluate_chapter, count_chapter_words
        from app.services.agents.tools.illustration_tools import insert_chapter_illustration
        from app.services.agents.tools.character_relation_tools import character_relation_tools
        from app.services.agents.tools.todo_tools import todo_tools

        return query_tools + node_tools + [write_chapter, edit_chapter_content, evaluate_chapter, count_chapter_words, insert_chapter_illustration] + character_relation_tools + todo_tools

    def _load_model_pref(self, user_id: str | None) -> dict | None:
        """读取用户的主/备模型偏好；未设或无 user_id 返回 None。"""
        if not user_id:
            return None
        db = _get_db()
        try:
            user = db.query(User).filter_by(id=user_id).first()
            if not user:
                return None
            return {"primary": user.primary_model, "fallback": user.fallback_model}
        finally:
            db.close()

    def _load_chat_history(self, session_id):
        """加载 session 历史（含 tool_call / tool_result），排除当前轮 user 避免重复。"""
        if not session_id:
            return []
        from app.services.session_store import session_store
        from app.services.message_langchain import db_message_dicts_to_langchain

        msgs = session_store.get_messages(session_id)
        conv = list(msgs)
        if conv and conv[-1].get("role") == "user":
            conv = conv[:-1]
        return db_message_dicts_to_langchain(conv)

    def _build_graph(self, model_pref: dict | None = None, session_id: str | None = None, work_id: str | None = None):
        """构建LangGraph"""
        tools = self._get_tools()
        tool_node = ToolNode(tools)

        primary = model_pref.get("primary") if model_pref else None
        fallback = model_pref.get("fallback") if model_pref else None
        llm = get_llm(temperature=0.5, primary=primary, fallback=fallback)
        llm_with_tools = bind_tools_to_llm(llm, tools)

        async def agent_node(state: SupervisorState):
            """Agent 节点：流式推送 reasoning + content，并返回完整 AIMessage。"""
            messages = list(state["messages"])
            response = None

            for parse_attempt in range(MAX_TOOL_CALL_PARSE_RETRIES + 1):
                if self.emit:
                    label = "AI 思考中" if parse_attempt == 0 else "修复工具参数"
                    await self.emit("stage_start", {"stage": "thinking", "label": label})

                aggregated = None
                async for chunk in llm_with_tools.astream(messages):
                    aggregated = chunk if aggregated is None else aggregated + chunk
                    if self.emit:
                        await emit_llm_stream_deltas(self.emit, "supervisor_stream", chunk)

                if aggregated is None:
                    raise RuntimeError("LLM 未返回任何响应")

                diagnostic = _tool_call_diagnostic_payload(aggregated)
                has_unparsed_tool_call = (
                    diagnostic["finish_reason"] == "tool_calls"
                    and diagnostic["tool_calls_count"] == 0
                    and (
                        diagnostic["invalid_tool_calls_count"] > 0
                        or diagnostic["tool_call_chunks_count"] > 0
                    )
                )

                response = chunk_to_ai_message(aggregated)
                if not response.tool_calls:
                    extracted = extract_tool_calls(response)
                    if extracted:
                        response = AIMessage(
                            content=response.content,
                            tool_calls=[
                                {
                                    "name": tc["name"],
                                    "args": tc.get("args") or {},
                                    "id": tc.get("id") or f"call_auto_{uuid.uuid4().hex[:12]}",
                                }
                                for tc in extracted
                            ],
                            additional_kwargs=getattr(response, "additional_kwargs", None) or {},
                        )

                if has_unparsed_tool_call and not response.tool_calls:
                    logger.warning(
                        "supervisor streaming tool call was not parsed session_id=%s work_id=%s attempt=%s diagnostic=%s",
                        session_id,
                        work_id,
                        parse_attempt + 1,
                        diagnostic,
                    )
                    if parse_attempt < MAX_TOOL_CALL_PARSE_RETRIES:
                        feedback = _build_tool_call_parse_feedback(aggregated)
                        messages.append(HumanMessage(content=feedback))
                        continue

                break

            if response is None:
                raise RuntimeError("LLM 未返回任何响应")

            if self.emit and response.tool_calls:
                tool_names = [tc.get("name", "") for tc in response.tool_calls if tc.get("name")]
                if tool_names:
                    await self.emit("tool_calls", {"tools": tool_names})
                    await self.emit(
                        "stage_start",
                        {"stage": "tool_calling", "label": f"调用工具: {tool_names[0]}"},
                    )

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
            self.emit = emit

            work_id = context.get("work_id") if context else None
            session_id = context.get("session_id") if context else None
            user_id = context.get("user_id") if context else None
            context_node_ids = context.get("context_node_ids") if context else None

            model_pref = self._load_model_pref(user_id)
            if context:
                context["emit"] = emit
                context["model_pref"] = model_pref
                set_context(context)

            graph = self._build_graph(model_pref=model_pref, session_id=session_id, work_id=work_id)

            system_prompt = self._build_system_prompt(context_node_ids=context_node_ids)

            # 注入历史对话（多轮），让 agent 看到上文，理解"需要/好/不用了"等省略回答
            chat_history = self._load_chat_history(session_id)

            initial_state = {
                "messages": [
                    SystemMessage(content=system_prompt),
                    *chat_history,
                    HumanMessage(content=user_message),
                ],
                "user_message": user_message,
            }

            # 与 main 分支一致：graph.astream 执行，流式输出在 agent_node 内完成
            graph_config = {"recursion_limit": 100}
            run_messages: list = []

            async for event in graph.astream(initial_state, config=graph_config):
                for node_name, node_output in event.items():
                    run_messages = _collect_messages_from_graph_event(
                        run_messages, node_name, node_output
                    )
                    if node_name == "tools" and self.emit:
                        for msg in node_output.get("messages", []):
                            if isinstance(msg, ToolMessage):
                                content = msg.content if hasattr(msg, "content") else str(msg)
                                await self.emit(
                                    "tool_executed",
                                    {
                                        "tool": getattr(msg, "name", "unknown"),
                                        "success": tool_message_success(str(content)),
                                    },
                                )

                    if session_id and node_name == "agent":
                        for msg in node_output.get("messages", []):
                            if isinstance(msg, AIMessage):
                                self._save_intermediate_messages(session_id, [msg], work_id)

                    if session_id and node_name == "tools":
                        tool_msgs = [
                            m for m in node_output.get("messages", [])
                            if isinstance(m, ToolMessage)
                        ]
                        if tool_msgs:
                            self._sync_tool_call_results(session_id, tool_msgs)
                            self._save_tool_results(session_id, tool_msgs, work_id)

            last_message = run_messages[-1] if run_messages else None

            if session_id and not run_messages:
                logger.warning(
                    "supervisor.run no messages to persist session_id=%s",
                    session_id,
                )

            result = {
                "success": True,
                "message": extract_text_content(getattr(last_message, "content", "")) if last_message else "",
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

    def _save_intermediate_messages(self, session_id: str, messages: list, work_id: str = None):
        """保存中间过程（assistant 文本 / tool_call）到数据库；不保存 tool_result。"""
        from app.services.session_store import session_store

        for idx, msg in enumerate(messages):
            if isinstance(msg, AIMessage):
                text = extract_text_content(msg.content)
                tool_calls = extract_tool_calls(msg)
                if not tool_calls and getattr(msg, "tool_calls", None):
                    tool_calls = [
                        {
                            "id": tc.get("id", ""),
                            "name": tc.get("name", ""),
                            "args": tc.get("args") or {},
                        }
                        for tc in msg.tool_calls
                        if isinstance(tc, dict)
                    ]
                is_final = len(messages) == 1 and idx == len(messages) - 1 and not tool_calls
                rc = getattr(msg, "additional_kwargs", {}).get("reasoning_content")
                tool_results = lookup_tool_results_after(messages, idx + 1)

                if text or rc:
                    save_meta = {"phase": "final" if is_final else "intermediate"}
                    if rc:
                        save_meta["reasoning_content"] = rc
                    session_store.add_message(
                        session_id,
                        role="assistant",
                        content=text or "",
                        meta=save_meta,
                        work_id=work_id,
                    )

                for tc in tool_calls:
                    call_id = tc.get("id", "")
                    tool_name = tc.get("name", "")
                    result_msg = tool_results.get(call_id) or tool_results.get(tool_name)
                    result_content = (
                        str(result_msg.content)
                        if result_msg and hasattr(result_msg, "content")
                        else ""
                    )
                    tc_meta = {
                        "args": tc.get("args", {}),
                        "tool_call_id": call_id,
                        "success": tool_message_success(result_content) if result_msg else True,
                    }
                    rc = getattr(msg, "additional_kwargs", {}).get("reasoning_content")
                    if rc:
                        tc_meta["reasoning_content"] = rc
                    session_store.add_message(
                        session_id,
                        role="tool_call",
                        content=tool_name,
                        meta=tc_meta,
                        work_id=work_id,
                    )
                continue

            if isinstance(msg, ToolMessage):
                continue

    def _save_tool_results(self, session_id: str, tool_messages: list, work_id: str = None):
        """持久化 tool_result 到数据库，供多轮上下文注入。"""
        from app.services.session_store import session_store

        for msg in tool_messages:
            if not isinstance(msg, ToolMessage):
                continue
            content = msg.content if hasattr(msg, "content") else str(msg)
            session_store.add_message(
                session_id,
                role="tool_result",
                content=content if isinstance(content, str) else str(content),
                meta={
                    "tool_call_id": getattr(msg, "tool_call_id", "") or "",
                    "tool_name": getattr(msg, "name", "") or "",
                },
                work_id=work_id,
            )

    def _sync_tool_call_results(self, session_id: str, tool_messages: list):
        """tools 节点完成后，回写 tool_call 的 success 状态。"""
        from app.services.session_store import session_store

        for msg in tool_messages:
            if not isinstance(msg, ToolMessage):
                continue
            content = msg.content if hasattr(msg, "content") else str(msg)
            session_store.patch_tool_call_success(
                session_id,
                call_id=getattr(msg, "tool_call_id", "") or "",
                tool_name=getattr(msg, "name", "") or "",
                success=tool_message_success(str(content)),
            )


# 单例
supervisor_agent = SupervisorAgent()
