"""Supervisor Agent - 主编排Agent"""
import json
import logging
import uuid
import asyncio
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Callable, Optional, Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from langsmith import traceable

from services.agents.llm import get_llm, bind_tools_to_llm, should_continue
from langgraph.errors import GraphRecursionError

from services.agents.supervisor_turn import (
    MAX_SUPERVISOR_TURN_RETRIES,
    SUPERVISOR_TOOL_LIMIT_INSTRUCTION,
    SUPERVISOR_TURN_RETRY_INSTRUCTION,
    count_current_run_work_tool_calls,
    count_supervisor_work_tool_calls,
    get_supervisor_iteration_limits,
    prepare_supervisor_ai_message,
)
from services.llm_stream import chunk_to_ai_message, emit_llm_stream_deltas
from services.message_content_utils import extract_text_content, extract_tool_calls
from services.tool_result_utils import lookup_tool_results_after, tool_message_success
from services.thinking_llm import has_meaningful_ai_output
from models.user import User


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


async def wrap_up_supervisor_after_tool_limit(
    messages: list,
    *,
    llm,
    emit: Optional[Callable] = None,
) -> AIMessage:
    """工具轮次或图递归触顶后，只允许 respond_to_user 给出用户可见回复。"""
    from services.agents.tools.respond_to_user_tool import respond_to_user

    bound = bind_tools_to_llm(llm, [respond_to_user])
    working = list(messages) + [HumanMessage(content=SUPERVISOR_TOOL_LIMIT_INSTRUCTION)]
    turn_retry = 0
    while True:
        if emit:
            await emit("stage_start", {"stage": "thinking", "label": "本轮工具次数已用尽，正在汇总回复"})
        aggregated = None
        async for chunk in bound.astream(working):
            aggregated = chunk if aggregated is None else aggregated + chunk
            if emit:
                await emit_llm_stream_deltas(emit, "supervisor_stream", chunk)
        if aggregated is None:
            raise RuntimeError("LLM 未返回任何响应")
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
        action, response = prepare_supervisor_ai_message(response)
        if action == "end":
            return response
        if turn_retry >= MAX_SUPERVISOR_TURN_RETRIES:
            raise RuntimeError("Agent stopped repeatedly without acting")
        turn_retry += 1
        working.append(response)
        working.append(HumanMessage(content=SUPERVISOR_TOOL_LIMIT_INSTRUCTION))


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


def _structured_tool_error(exc: Exception) -> str:
    """把工具参数校验错误作为稳定契约返回给 Supervisor。"""
    fields = []
    errors = getattr(exc, "errors", None)
    if callable(errors):
        for item in errors():
            location = item.get("loc") or []
            fields.append({
                "path": ".".join(str(part) for part in location),
                "message": item.get("msg") or str(exc),
                "type": item.get("type") or "validation_error",
            })
    return json.dumps({
        "success": False,
        "status": "failed",
        "error": {
            "code": "tool_argument_validation_failed",
            "message": "工具参数不符合 Schema",
            "fields": fields or [{"path": "", "message": str(exc), "type": "validation_error"}],
        },
    }, ensure_ascii=False)


def _get_db():
    from database import SessionLocal
    return SessionLocal()


# 请求级上下文必须随异步任务隔离，不能由并发 Agent 共享。
_current_context: ContextVar[Dict[str, Any] | None] = ContextVar(
    "supervisor_context",
    default=None,
)


def set_context(context: Dict[str, Any]) -> Token:
    """设置当前上下文"""
    return _current_context.set(context)


def reset_context(token: Token) -> None:
    """恢复设置前的请求上下文。"""
    _current_context.reset(token)


def get_context() -> Dict[str, Any]:
    """获取当前上下文"""
    context = _current_context.get()
    return context if context is not None else {}


class SupervisorState(MessagesState):
    """Supervisor状态"""


class SupervisorAgent:
    """Supervisor Agent - 主编排Agent"""

    def __init__(self, emit: Optional[Callable] = None):
        self._default_emit = emit

    def _build_system_prompt(self) -> str:
        """构建稳定的头部 system A（会话内不因轮次参数改写）。"""
        template_path = PROMPT_DIR / "supervisor_system.txt"
        template = template_path.read_text(encoding="utf-8")
        return template.replace("{context_section}", "")

    def _build_in_history_system_prompt(
        self,
        context_node_ids: list | None = None,
        chapter_review_intensity: str = "medium",
    ) -> str | None:
        """轮次差异：追加在历史之后，避免改写头部 system 导致 prefix cache 失效。"""
        parts: list[str] = []
        if context_node_ids:
            ids_list = "\n".join(f"- {nid}" for nid in context_node_ids)
            parts.append(
                "## 用户指定的对话上下文\n"
                "用户已把以下节点标记为本对话的重点上下文，请优先用 read_node_content 读取它们的内容，作为本次对话的核心参考：\n"
                f"{ids_list}"
            )

        review_instructions = {
            "low": (
                "本次章节评审强度为低：不调用任何评审工具，"
                "完成创作、摘要和提交。本条覆盖系统提示中的默认中档。"
            ),
            "high": (
                "本次章节评审强度为高：评审次数不限，各评审 Agent 会以严苛的读者视角给出建议。"
                "由你判断建议是否值得采纳；值得采纳时修订并对最新草稿复检，"
                "直到评审建议无需采纳，或评审 Agent 明确认为文本已经优秀。"
                "本条覆盖系统提示中的默认中档。"
            ),
        }
        if chapter_review_intensity in review_instructions:
            parts.append(review_instructions[chapter_review_intensity])

        if not parts:
            return None
        return "\n\n".join(parts)

    def _assemble_initial_messages(
        self,
        history: list,
        current_turn: list,
        context_node_ids: list | None = None,
        chapter_review_intensity: str = "medium",
        session_id: str | None = None,
        before_message_id: str | None = None,
    ) -> list:
        base_prompt = self._build_system_prompt()
        messages = [SystemMessage(content=base_prompt), *history]
        in_history = self._build_in_history_system_prompt(
            context_node_ids=context_node_ids,
            chapter_review_intensity=chapter_review_intensity,
        )
        effective_prompt = f"{base_prompt}\n\n{in_history}" if in_history else base_prompt
        previous_prompt = next((
            message.content for message in reversed(history)
            if isinstance(message, SystemMessage)
            and message.additional_kwargs.get("type") == "system_prompt_update"
        ), base_prompt)
        if effective_prompt != previous_prompt:
            meta = {"type": "system_prompt_update"}
            if session_id:
                from services.session_store import session_store
                session_store.add_message(
                    session_id, role="system", content=effective_prompt,
                    meta=meta, before_message_id=before_message_id,
                )
            messages.append(SystemMessage(content=effective_prompt, additional_kwargs=meta))
        messages.extend(current_turn)
        return messages

    def _get_tools(self):
        """单 Agent：直接挂全部操作工具，不再 dispatch 到子 agent。"""
        from services.agents.tools.query_tools import query_tools
        from services.agents.tools.node_tools import node_tools
        from services.agents.tools.chapter_tools import evaluate_chapter, count_chapter_words
        from services.agents.tools.illustration_tools import insert_chapter_illustration
        from services.agents.tools.character_relation_tools import character_relation_tools
        from services.agents.tools.context_tools import context_tools
        from services.agents.tools.research_tools import research_tools
        from services.agents.tools.humanizer_tools import humanizer_tools
        from services.agents.tools.specialist_agent_tools import specialist_agent_tools
        from services.agents.tools.workflow_agent_tools import workflow_agent_tools
        from services.agents.tools.respond_to_user_tool import respond_to_user

        return [respond_to_user] + query_tools + node_tools + [evaluate_chapter, count_chapter_words, insert_chapter_illustration] + character_relation_tools + context_tools + research_tools + humanizer_tools + specialist_agent_tools + workflow_agent_tools

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
        """返回 (历史, 当前轮 user 消息 dicts)。

        历史已排除末尾连续的 user 消息（当前轮），并应用压缩包替换。
        当前轮 user 消息（1 条纯文字，或 2 条操作+文字）单独返回，供 run 拼到
        initial_state 末尾，保证顺序与持久化一致。
        """
        if not session_id:
            return [], []
        from services.session_store import session_store
        from services.message_langchain import db_message_dicts_to_langchain
        from services.agents.tools.context_tools import _compact_message_for_llm

        msgs = session_store.get_messages(session_id)
        conv = [
            msg for msg in msgs
            if not (
                isinstance(msg.get("meta"), dict)
                and msg["meta"].get("type") == "user_canvas_actions"
                and msg["meta"].get("excluded_from_agent") is True
            )
        ]
        # 收集末尾连续的 user 消息（当前轮）
        current_turn = []
        while conv and conv[-1].get("role") == "user":
            current_turn.insert(0, conv.pop())

        compaction = session_store.get_active_context_compaction(session_id)
        if compaction:
            compact_order = compaction.get("sort_order", -1)
            after = []
            for msg in conv:
                if msg.get("sort_order", -1) <= compact_order:
                    continue
                meta = msg.get("meta") if isinstance(msg.get("meta"), dict) else {}
                if meta.get("type") == "context_compaction":
                    continue
                if msg.get("role") == "tool_call" and msg.get("content") == "create_context_compaction":
                    continue
                if msg.get("role") == "tool_result" and meta.get("tool_name") == "create_context_compaction":
                    continue
                after.append(msg)
            history = [
                SystemMessage(content=_compact_message_for_llm(compaction)),
                *db_message_dicts_to_langchain(after),
            ]
        else:
            history = db_message_dicts_to_langchain(conv)

        return history, current_turn

    def _build_graph(
        self,
        model_pref: dict | None = None,
        session_id: str | None = None,
        work_id: str | None = None,
        emit: Optional[Callable] = None,
        chapter_review_intensity: str = "medium",
    ):
        """构建LangGraph"""
        emit = emit or self._default_emit
        tool_call_limit, _ = get_supervisor_iteration_limits(chapter_review_intensity)
        tools = self._get_tools()
        tool_node = ToolNode(tools, handle_tool_errors=_structured_tool_error)

        primary = model_pref.get("primary") if model_pref else None
        fallback = model_pref.get("fallback") if model_pref else None
        llm = get_llm(temperature=0.5, primary=primary, fallback=fallback)
        llm_with_tools = bind_tools_to_llm(llm, tools)
        from services.agents.tools.respond_to_user_tool import respond_to_user
        llm_end_only = bind_tools_to_llm(llm, [respond_to_user])
        run_start_work_tool_calls: int | None = None

        async def agent_node(state: SupervisorState):
            """Agent 节点：流式推送 reasoning + content，并返回完整 AIMessage。"""
            nonlocal run_start_work_tool_calls
            messages = list(state["messages"])
            response = None
            parse_attempt = 0
            turn_retry = 0
            total_work_tool_calls = count_supervisor_work_tool_calls(messages)
            if run_start_work_tool_calls is None:
                run_start_work_tool_calls = total_work_tool_calls
            current_run_work_tool_calls = count_current_run_work_tool_calls(
                messages,
                run_start_work_tool_calls,
            )
            hit_limit = current_run_work_tool_calls >= tool_call_limit
            active_llm = llm_end_only if hit_limit else llm_with_tools
            if hit_limit:
                messages.append(HumanMessage(content=SUPERVISOR_TOOL_LIMIT_INSTRUCTION))

            while True:
                if emit:
                    if parse_attempt > 0:
                        label = "修复工具参数"
                    elif turn_retry > 0:
                        label = "继续执行"
                    else:
                        label = "AI 思考中"
                    await emit("stage_start", {"stage": "thinking", "label": label})

                aggregated = None
                from services.agents.sampling_override import supervisor_sampling_scope
                with supervisor_sampling_scope(active_llm):
                    async for chunk in active_llm.astream(messages):
                        aggregated = chunk if aggregated is None else aggregated + chunk
                        if emit:
                            await emit_llm_stream_deltas(emit, "supervisor_stream", chunk)

                if aggregated is None:
                    raise RuntimeError("LLM 未返回任何响应")

                usage = getattr(aggregated, "usage_metadata", None)
                if usage:
                    ctx = get_context()
                    ctx["last_llm_usage"] = usage

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

                if not has_meaningful_ai_output(response):
                    raise RuntimeError("主模型和备用模型均返回空响应")

                if has_unparsed_tool_call and not response.tool_calls:
                    logger.warning(
                        "supervisor streaming tool call was not parsed session_id=%s work_id=%s attempt=%s diagnostic=%s",
                        session_id,
                        work_id,
                        parse_attempt + 1,
                        diagnostic,
                    )
                    if parse_attempt < MAX_TOOL_CALL_PARSE_RETRIES:
                        parse_attempt += 1
                        feedback = _build_tool_call_parse_feedback(aggregated)
                        messages.append(HumanMessage(content=feedback))
                        continue

                action, response = prepare_supervisor_ai_message(response)
                logger.info(
                    "supervisor turn action=%s response.text=%s tool_calls=%s finish_reason=%s retry_count=%s",
                    action,
                    extract_text_content(response.content),
                    [tc.get("name") for tc in (response.tool_calls or [])],
                    diagnostic.get("finish_reason"),
                    turn_retry,
                )
                if action == "retry":
                    if turn_retry >= MAX_SUPERVISOR_TURN_RETRIES:
                        raise RuntimeError("Agent stopped repeatedly without acting")
                    turn_retry += 1
                    messages.append(response)
                    messages.append(HumanMessage(content=SUPERVISOR_TURN_RETRY_INSTRUCTION))
                    continue
                break

            if response is None:
                raise RuntimeError("LLM 未返回任何响应")

            if emit and response.tool_calls:
                tool_calls = [
                    {"id": tc.get("id", ""), "name": tc.get("name", "")}
                    for tc in response.tool_calls
                    if tc.get("name")
                ]
                if tool_calls:
                    await emit("tool_calls", {"tools": tool_calls})
                    await emit(
                        "stage_start",
                        {"stage": "tool_calling", "label": f"调用工具: {tool_calls[0]['name']}"},
                    )

            return {"messages": [response]}

        async def atomic_tools_node(state: SupervisorState):
            from services.tool_execution_unit import run_atomic_tool_calls
            return await run_atomic_tool_calls(
                tool_node=tool_node,
                state=state,
                work_id=work_id,
                session_id=session_id,
            )

        graph = StateGraph(SupervisorState)
        graph.add_node("agent", agent_node)
        graph.add_node("tools", atomic_tools_node)

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
        context_token = None
        run_emit = emit or self._default_emit
        session_id = (context or {}).get("session_id")
        work_id = (context or {}).get("work_id")
        try:
            run_context = dict(context or {})

            work_id = run_context.get("work_id")
            session_id = run_context.get("session_id")
            user_id = run_context.get("user_id")
            context_node_ids = run_context.get("context_node_ids")

            model_pref = self._load_model_pref(user_id)
            run_context["emit"] = run_emit
            run_context["model_pref"] = model_pref
            context_token = set_context(run_context)

            chapter_review_intensity = run_context.get("chapter_review_intensity", "medium")
            _, graph_recursion_limit = get_supervisor_iteration_limits(
                chapter_review_intensity
            )
            graph = self._build_graph(
                model_pref=model_pref,
                session_id=session_id,
                work_id=work_id,
                emit=run_emit,
                chapter_review_intensity=chapter_review_intensity,
            )

            # 注入历史对话（多轮），让 agent 看到上文，理解"需要/好/不用了"等省略回答
            chat_history, current_turn_msgs = self._load_chat_history(session_id)
            from services.message_langchain import db_message_dicts_to_langchain
            current_turn = db_message_dicts_to_langchain(current_turn_msgs)
            if not current_turn:
                current_turn = [HumanMessage(content=user_message)]

            initial_state = {
                "messages": self._assemble_initial_messages(
                    chat_history,
                    current_turn,
                    context_node_ids=context_node_ids,
                    chapter_review_intensity=chapter_review_intensity,
                    session_id=session_id,
                    before_message_id=current_turn_msgs[0]["id"] if current_turn_msgs else None,
                ),
            }

            # 与 main 分支一致：graph.astream 执行，流式输出在 agent_node 内完成
            graph_config = {"recursion_limit": graph_recursion_limit}
            run_messages: list = []

            try:
                async for event in graph.astream(initial_state, config=graph_config):
                    for node_name, node_output in event.items():
                        run_messages = _collect_messages_from_graph_event(
                            run_messages, node_name, node_output
                        )
                        if node_name == "tools" and run_emit:
                            for msg in node_output.get("messages", []):
                                if isinstance(msg, ToolMessage):
                                    content = msg.content if hasattr(msg, "content") else str(msg)
                                    await run_emit(
                                        "tool_executed",
                                        {
                                            "tool": getattr(msg, "name", "unknown"),
                                            "tool_call_id": getattr(msg, "tool_call_id", ""),
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
            except GraphRecursionError:
                logger.warning(
                    "supervisor tool/graph limit reached session_id=%s work_id=%s rounds=%s",
                    session_id,
                    work_id,
                    count_supervisor_work_tool_calls(run_messages),
                )
                wrap_source = list(initial_state["messages"]) + list(run_messages)
                wrap_primary = model_pref.get("primary") if model_pref else None
                wrap_fallback = model_pref.get("fallback") if model_pref else None
                wrap_ai = await wrap_up_supervisor_after_tool_limit(
                    wrap_source,
                    llm=get_llm(temperature=0.5, primary=wrap_primary, fallback=wrap_fallback),
                    emit=run_emit,
                )
                run_messages = [*wrap_source, wrap_ai]
                if session_id:
                    self._save_intermediate_messages(session_id, [wrap_ai], work_id)

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

            workflow_gate = get_context().get("workflow_gate")
            if isinstance(workflow_gate, dict):
                result["workflow_status"] = workflow_gate.get("status")
                result["workflow_gate"] = workflow_gate

            if run_emit:
                await run_emit("supervisor_done", {
                    "message": result["message"],
                    "workflow_status": result.get("workflow_status", "completed"),
                    "workflow_gate": result.get("workflow_gate"),
                })

            return result

        except asyncio.CancelledError:
            from services.session_store import session_store as _session_store
            from services.tool_execution_unit import rollback_active_tool_unit
            had_unit = get_context().get("active_tool_unit") is not None
            rollback_active_tool_unit()
            if session_id:
                _session_store.discard_unpaired_tool_calls(session_id)
            if had_unit:
                await run_emit("nodes_updated", {"action": "tool_interrupted"})
            logger.info(
                "supervisor run cancelled session_id=%s work_id=%s",
                session_id,
                work_id,
            )
            raise
        except Exception as e:
            logger.error(f"SupervisorAgent error: {e}")
            return {
                "success": False,
                "error": str(e),
            }
        finally:
            if context_token is not None:
                reset_context(context_token)

    def _save_intermediate_messages(self, session_id: str, messages: list, work_id: str = None):
        """保存中间过程（assistant 文本 / tool_call）到数据库；不保存 tool_result。"""
        from services.session_store import session_store

        for idx, msg in enumerate(messages):
            if isinstance(msg, AIMessage):
                # 模型历史独立保存完整消息，展示行只用于 UI，避免跨轮拆分或合并 assistant。
                session_store.add_message(
                    session_id, role="model_assistant",
                    content=msg.model_dump_json(), work_id=work_id,
                )
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
                    save_meta = {"phase": "final" if is_final else "intermediate", "presentation_only": True}
                    if rc:
                        save_meta["reasoning_content"] = rc
                    usage = getattr(msg, "usage_metadata", None)
                    if usage:
                        save_meta["usage_metadata"] = usage
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
                        "presentation_only": True,
                        "args": tc.get("args", {}),
                        "tool_call_id": call_id,
                        "success": tool_message_success(result_content) if result_msg else True,
                    }
                    usage = getattr(msg, "usage_metadata", None)
                    if usage:
                        tc_meta["usage_metadata"] = usage
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
        from services.session_store import session_store

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
        from services.session_store import session_store

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
