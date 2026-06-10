"""ChapterAgent — 统一的章节撰写与编辑子 Agent

合并原 ChapterAgentGraph（新写章节）和 EditChapterAgent（编辑章节），
由 LLM 根据任务自主决定写新章还是编辑已有章节。
"""

from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolNode
from sqlalchemy.orm import Session

from app.services.supervisor.sub_agent_base import (
    astream_agent_llm_to_message,
    bind_agent_llm_with_tools,
    get_llm,
)
from app.services.supervisor.tool_registry import build_chapter_agent_tools
from app.services.supervisor.prompt_builder import inject_child_todolist_sections
from app.services.stream_trace import gap_log

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"


# ── 状态定义 ──


class ChapterAgentState(MessagesState):
    """ChapterAgent 在 LangGraph StateGraph 中传递的状态"""

    work_id: str
    chapter_number: int | None
    user_message: str
    auto_mode: bool = True


# ── System Prompt ──


def _build_system_prompt(
    work_id: str,
    chapter_number: int | None,
    user_message: str,
    is_new_chapter: bool | None,
    auto_mode: bool,
    *,
    enable_child_todolist: bool,
) -> str:
    """构建 ChapterAgent 的 system prompt"""
    template = (PROMPT_DIR / "chapter_agent_system.txt").read_text(encoding="utf-8")
    template = inject_child_todolist_sections(template, enabled=enable_child_todolist)
    mode_desc = "自动模式：所有操作直接执行，不需要等待确认。" if auto_mode else "交互模式：完成关键步骤后可能需要等待用户确认。"
    if is_new_chapter is True:
        task_type = "撰写新章节"
    elif is_new_chapter is False:
        task_type = "编辑已有章节"
    else:
        task_type = "由任务文本和工具调用自行判断"

    if chapter_number is None:
        target_description = "未由系统固定；请从 Supervisor 下派任务中判断目标章节，并在每次章节工具调用时显式传入 chapter_number。"
        boundary_rule = (
            "你必须完全遵守 Supervisor 下派的任务边界。"
            "如果任务要求写第N章，调用章节工具时就必须传入 chapter_number=N；"
            "不要因为文本中出现“第M章结尾/前文/大纲”等上下文引用而把目标章节改成第M章。"
        )
        chapter_number_plus_one = "N+1"
    else:
        target_description = f"第{chapter_number}章"
        boundary_rule = (
            f"你必须完全遵守 Supervisor 下派的章节号和任务类型。当前任务是第{chapter_number}章，"
            f"就只能处理第{chapter_number}章；不得因为该章已存在而自行改写为第{chapter_number + 1}章或“下一章”。"
        )
        chapter_number_plus_one = chapter_number + 1

    return template.format(
        work_id=work_id,
        chapter_number=chapter_number if chapter_number is not None else "未固定",
        chapter_number_plus_one=chapter_number_plus_one,
        target_description=target_description,
        boundary_rule=boundary_rule,
        user_message=user_message,
        task_type=task_type,
        mode_description=mode_desc,
    )


# ── Agent Node ──


def _make_chapter_agent_node(tools, *, emit, stream_event: str):
    async def _chapter_agent_node(state: ChapterAgentState) -> dict:
        """LLM 节点"""
        llm = get_llm(temperature=0.7)
        llm_with_tools = bind_agent_llm_with_tools(llm, tools)

        messages = state.get("messages", [])

        has_system = any(isinstance(m, SystemMessage) for m in messages)
        if not has_system:
            system_prompt = state.get("_system_prompt", "")
            full_messages = [SystemMessage(content=system_prompt)] + messages
        else:
            full_messages = messages

        response = await astream_agent_llm_to_message(
            llm_with_tools,
            full_messages,
            emit=emit,
            stream_event=stream_event,
        )
        return {"messages": [response]}

    return _chapter_agent_node


# ── 条件边 ──


def _should_continue(state: ChapterAgentState) -> str:
    """条件边：判断 LLM 是否还在调用工具"""
    messages = state.get("messages", [])
    if not messages:
        return END
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# ── ChapterAgent 类 ──


class ChapterAgent:
    """统一章节 Agent — 同时支持撰写新章和编辑已有章节"""

    def __init__(self, emit: Callable):
        self.emit = emit

    def _build_graph(self, tools, *, stream_event: str):
        """构建 LangGraph StateGraph"""
        graph = StateGraph(ChapterAgentState)
        graph.add_node("agent", _make_chapter_agent_node(tools, emit=self.emit, stream_event=stream_event))
        graph.add_node("tools", ToolNode(tools))

        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")

        return graph.compile()

    async def run(
        self,
        work_id: str,
        user_message: str,
        db: Session,
        *,
        chapter_number: int | None = None,
        is_new_chapter: bool | None = True,
        auto_mode: bool = True,
        db_lock: object | None = None,
        base_configurable: dict | None = None,
        emit_diff_event: bool = True,
        pre_edit_content: str | None = None,
    ) -> dict:
        """执行章节任务（新写或编辑）。

        Args:
            is_new_chapter: True=撰写新章节，False=编辑已有章节。
        """
        if chapter_number is None:
            stage_label = "处理章节任务"
        else:
            stage_label = f"写第{chapter_number}章" if is_new_chapter else f"处理第{chapter_number}章"
        self.emit("stage_start", {"stage": "chapter_agent", "label": stage_label})

        configurable = dict(base_configurable or {})
        gap_log(
            "chapter_agent_run_begin",
            session_id=configurable.get("supervisor_session_id"),
            t0=configurable.get("gap_trace_t0"),
            chapter_number=chapter_number,
            is_new_chapter=is_new_chapter,
        )

        enable_child_todolist = bool(configurable.get("enable_child_todolist", False))
        tools = build_chapter_agent_tools(enable_child_todolist=enable_child_todolist)
        stream_event = "write_stream" if is_new_chapter else "edit_chapter_stream"
        graph = self._build_graph(tools, stream_event=stream_event)

        configurable.update({
            "db": db,
            "emit": self.emit,
            "db_lock": db_lock,
            "work_id": work_id,
            "chapter_number": chapter_number,
        })
        config = {
            "configurable": configurable,
            "recursion_limit": 100,
        }

        system_prompt = _build_system_prompt(
            work_id=work_id,
            chapter_number=chapter_number,
            user_message=user_message,
            is_new_chapter=is_new_chapter,
            auto_mode=auto_mode,
            enable_child_todolist=enable_child_todolist,
        )

        initial_state = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ],
            "work_id": work_id,
            "chapter_number": chapter_number,
            "user_message": user_message,
            "auto_mode": auto_mode,
            "_system_prompt": system_prompt,
        }

        from app.services.supervisor.session_interrupt import (
            INTERRUPTED_USER_MESSAGE,
            check_session_interrupted,
        )

        final_state = None
        all_messages: list = []
        async for event in graph.astream(initial_state, config=config):
            if check_session_interrupted(config):
                self.emit("supervisor_interrupted", {"message": INTERRUPTED_USER_MESSAGE})
                return {"message": f"（{INTERRUPTED_USER_MESSAGE.rstrip('。')}）", "interrupted": True}

            for node_name, node_output in event.items():
                if node_name == "tools":
                    if isinstance(node_output, dict):
                        tool_msgs = node_output.get("messages", [])
                        all_messages = _collect_messages_from_graph_event(
                            all_messages, "tools", node_output
                        )
                        for tm in tool_msgs:
                            content = tm.content if hasattr(tm, "content") else str(tm)
                            self.emit("tool_result", {
                                "tool_name": getattr(tm, "name", "unknown"),
                                "tool_call_id": getattr(tm, "tool_call_id", ""),
                                "content": str(content),
                            })
                            self.emit("tool_executed", {
                                "tool": getattr(tm, "name", "unknown"),
                            })
                    continue
                all_messages = _collect_messages_from_graph_event(
                    all_messages, node_name, node_output
                )
                if node_name == "agent" and isinstance(node_output, dict):
                    final_state = node_output
                    msgs = node_output.get("messages", [])
                    for m in msgs:
                        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                            for tc in m.tool_calls:
                                label = _format_tool_step_label(
                                    tc.get("name", "unknown"),
                                    chapter_number,
                                )
                                self.emit("stage_start", {
                                    "stage": "chapter_tool",
                                    "label": label,
                                })
                elif node_name == "messages" and isinstance(node_output, list):
                    final_state = {"messages": node_output}
                elif isinstance(node_output, dict) and "messages" in node_output:
                    final_state = node_output

        # 提取最终回复
        final_messages = all_messages or (
            final_state.get("messages", []) if isinstance(final_state, dict) else []
        )
        assistant_content = ""
        for msg in reversed(final_messages):
            if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                assistant_content = msg.content
                break

        if not assistant_content and final_messages:
            last = final_messages[-1]
            if isinstance(last, AIMessage):
                assistant_content = last.content or ""

        result = {"message": assistant_content}

        # 编辑模式下，尝试生成 diff。无固定章节号启动时，具体工具自行处理结果。
        if is_new_chapter is False and chapter_number is not None:
            old_content = _resolve_old_content_for_diff(
                final_messages=final_messages,
                pre_edit_content=pre_edit_content,
            )

            from app.models.work_model import Chapter

            db_chapter = db.query(Chapter).filter_by(
                work_id=work_id, chapter_number=chapter_number
            ).first()
            new_content_from_db = db_chapter.content if db_chapter else ""

            if old_content and new_content_from_db and old_content != new_content_from_db:
                diff_result = build_chapter_edit_diff_result(old_content, new_content_from_db)
                result.update(diff_result)

                if emit_diff_event:
                    self.emit("edit_chapter_diff", {
                        "diff": diff_result["diff"],
                        "summary": diff_result["summary"],
                        "old_content": old_content,
                        "new_content": new_content_from_db,
                        "chapter_number": chapter_number,
                    })

        return result

    def accept_edit(
        self,
        work_id: str,
        chapter_number: int,
        new_content: str,
        db: Session,
        emit_event: bool = True,
    ) -> dict:
        """用户接受修改 — 将新内容写入数据库"""
        from app.models.work_model import Chapter

        chapter = db.query(Chapter).filter_by(
            work_id=work_id, chapter_number=chapter_number
        ).first()
        if not chapter:
            return {"error": "章节不存在"}

        chapter.content = new_content
        chapter.status = "已保存"
        try:
            db.commit()
            db.refresh(chapter)
        except Exception as exc:
            db.rollback()
            return {"error": f"保存章节失败：{exc!r}"}

        word_count = len(new_content.replace("\n", "").replace(" ", ""))
        if emit_event:
            self.emit("edit_chapter_accepted", {
                "chapter_number": chapter_number,
                "title": chapter.title,
                "word_count": word_count,
            })
        return {"success": True, "title": chapter.title, "word_count": word_count}


# ── 辅助函数 ──


_TOOL_DISPLAY_NAMES = {
    "generate_patch_edit": "修改",
    "rewrite_chapter": "重写",
    "read_chapter": "读取",
    "query_characters_by_chapter": "查询角色",
    "grep_in_chapter": "搜索正文",
    "query_chapter_meta": "查询元数据",
    "grep_chapter_meta": "搜索元数据",
    "sync_chapter_metadata": "同步元数据",
    "overwrite_chapter_title": "修改标题",
    "count_chapter_words": "统计字数",
    "read_requirements_doc": "读取需求文档",
}


def _format_tool_step_label(tool_name: str, chapter_number: int | None) -> str:
    action = _TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
    if chapter_number is not None:
        return f"{action}第{chapter_number}章"
    return action


def _collect_messages_from_graph_event(
    all_messages: list,
    node_name: str,
    node_output,
) -> list:
    """从 graph.astream 单条事件中累积消息（兼容 updates / values 流）。"""
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


def _resolve_old_content_for_diff(
    *,
    final_messages: list,
    pre_edit_content: str | None,
) -> str:
    """解析用于 diff 的旧正文：优先编辑前 DB 快照，其次 read_chapter 工具结果。"""
    if pre_edit_content:
        return pre_edit_content
    for msg in final_messages:
        if getattr(msg, "name", None) == "read_chapter":
            extracted = _extract_content_from_read(msg.content)
            if extracted:
                return extracted
    return ""


def build_chapter_edit_diff_result(old_content: str, new_content: str) -> dict:
    """根据新旧正文生成 diff 结果字段。"""
    diff = _build_diff(old_content, new_content)
    summary = _summarize_diff(diff)
    return {
        "old_content": old_content,
        "new_content": new_content,
        "diff": diff,
        "summary": summary,
    }


def _extract_content_from_read(read_result: str) -> str:
    """从 read_chapter 工具返回的文本中提取正文内容"""
    marker_start = "--- 正文开始 ---"
    marker_end = "--- 正文结束 ---"
    start_idx = read_result.find(marker_start)
    end_idx = read_result.find(marker_end)
    if start_idx != -1 and end_idx != -1:
        return read_result[start_idx + len(marker_start):end_idx].strip()
    return ""


def _build_diff(old: str, new: str) -> list[dict]:
    """生成逐行 diff"""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    sm = difflib.SequenceMatcher(None, old_lines, new_lines)
    result = []
    old_no = 0
    new_no = 0

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                old_no += 1
                new_no += 1
                result.append({"type": "context", "line": old_lines[k].rstrip("\n"), "old_no": old_no, "new_no": new_no})
        elif tag == "replace":
            for k in range(i1, i2):
                old_no += 1
                result.append({"type": "removed", "line": old_lines[k].rstrip("\n"), "old_no": old_no})
            for k in range(j1, j2):
                new_no += 1
                result.append({"type": "added", "line": new_lines[k].rstrip("\n"), "new_no": new_no})
        elif tag == "insert":
            for k in range(j1, j2):
                new_no += 1
                result.append({"type": "added", "line": new_lines[k].rstrip("\n"), "new_no": new_no})
        elif tag == "delete":
            for k in range(i1, i2):
                old_no += 1
                result.append({"type": "removed", "line": old_lines[k].rstrip("\n"), "old_no": old_no})

    return result


def _summarize_diff(diff: list[dict]) -> dict:
    """统计 diff 摘要"""
    added = sum(1 for d in diff if d["type"] == "added")
    removed = sum(1 for d in diff if d["type"] == "removed")
    return {"lines_added": added, "lines_removed": removed, "total_changes": added + removed}
