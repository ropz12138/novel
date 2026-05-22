"""EditChapterAgent — 基于 LangGraph StateGraph + Tool-Calling 的章节编辑子 Agent

改造自原来的方法级封装，现在具备自主选择工具的能力：
- LLM 根据用户编辑需求，自主决定调用 read_chapter → grep_in_chapter → rewrite_chapter 等工具
- SupervisorAgent 只传递用户的原始编辑意图，子 Agent 自行决定如何完成
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolNode
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.supervisor.edit_chapter_tools import EDIT_CHAPTER_TOOLS
from app.services.supervisor.sub_agent_base import (
    chunk_to_ai_message,
    get_llm,
    run_agent_stream,
    stream_text_delta,
)

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"


# ── 状态定义 ──


class EditChapterState(MessagesState):
    """EditChapterAgent 在 LangGraph StateGraph 中传递的状态"""

    work_id: str
    chapter_number: int
    user_message: str


# ── System Prompt ──


def _build_edit_chapter_system_prompt(
    work_id: str,
    chapter_number: int,
    user_message: str,
) -> str:
    """构建 EditChapterAgent 的 system prompt"""
    template = (PROMPT_DIR / "edit_chapter_system.txt").read_text(encoding="utf-8")
    return template.format(
        work_id=work_id,
        chapter_number=chapter_number,
        user_message=user_message,
    )


# ── Agent Node ──


async def _edit_chapter_agent_node(state: EditChapterState) -> dict:
    """LLM 节点：接收 messages，流式输出，返回 AIMessage。

    system prompt 只在首次调用时注入（通过初始消息），
    后续轮次直接使用 state 中的 messages（已包含历史 tool 调用上下文）。
    """
    llm = get_llm(temperature=0.7)
    llm_with_tools = llm.bind_tools(EDIT_CHAPTER_TOOLS)

    messages = state.get("messages", [])

    # 检查是否已有 system prompt（首次调用时由 run() 注入到初始消息中）
    has_system = any(isinstance(m, SystemMessage) for m in messages)
    if not has_system:
        system_prompt = _build_edit_chapter_system_prompt(
            work_id=state.get("work_id", ""),
            chapter_number=state.get("chapter_number", 0),
            user_message=state.get("user_message", ""),
        )
        full_messages = [SystemMessage(content=system_prompt)] + messages
    else:
        full_messages = messages

    aggregated = None
    async for chunk in llm_with_tools.astream(full_messages):
        aggregated = chunk if aggregated is None else aggregated + chunk

    if aggregated is None:
        raise RuntimeError("EditChapterAgent LLM 未返回任何流式分片")

    response = chunk_to_ai_message(aggregated)
    return {"messages": [response]}


# ── 条件边 ──


def _should_continue(state: EditChapterState) -> str:
    """条件边：判断 LLM 是否还在调用工具"""
    messages = state.get("messages", [])
    if not messages:
        return END
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# ── EditChapterAgent 类 ──


class EditChapterAgent:
    """章节编辑 Agent — 使用 LangGraph StateGraph 编排 LLM 和工具调用"""

    def __init__(self, emit: Callable):
        self.emit = emit
        self._graph = None

    def _build_graph(self):
        """构建 LangGraph StateGraph"""
        graph = StateGraph(EditChapterState)
        graph.add_node("agent", _edit_chapter_agent_node)
        graph.add_node("tools", ToolNode(EDIT_CHAPTER_TOOLS))

        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")

        return graph.compile()

    async def run(
        self,
        work_id: str,
        chapter_number: int,
        user_message: str,
        db: Session,
        emit_diff_event: bool = True,
        db_lock: object | None = None,
    ) -> dict:
        """执行章节编辑任务。"""
        self.emit("stage_start", {"stage": "edit_chapter", "label": f"处理第{chapter_number}章"})

        graph = self._build_graph()

        config = {
            "configurable": {
                "db": db,
                "emit": self.emit,
                "db_lock": db_lock,
            },
            "recursion_limit": 25,
        }

        system_prompt = _build_edit_chapter_system_prompt(
            work_id=work_id,
            chapter_number=chapter_number,
            user_message=user_message,
        )

        initial_state = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ],
            "work_id": work_id,
            "chapter_number": chapter_number,
            "user_message": user_message,
        }

        final_state = None
        async for event in graph.astream(initial_state, config=config):
            for node_name, node_output in event.items():
                if node_name == "tools":
                    tool_msgs = node_output.get("messages", [])
                    for tm in tool_msgs:
                        content = tm.content if hasattr(tm, "content") else str(tm)
                        self.emit("tool_result", {
                            "tool_name": getattr(tm, "name", "unknown"),
                            "tool_call_id": getattr(tm, "tool_call_id", ""),
                            "content": str(content)[:500],
                        })
            final_state = node_output

        # 提取最终回复
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

        # 尝试从工具结果中提取 new_content 和 old_content 用于 diff
        old_content = ""
        new_content = ""
        for msg in final_messages:
            if hasattr(msg, "name") and msg.name == "read_chapter":
                old_content = _extract_content_from_read(msg.content)
            if hasattr(msg, "name") and msg.name in ("rewrite_chapter", "generate_patch_edit"):
                new_content = _extract_content_from_generate(msg.content)

        result = {
            "message": assistant_content,
        }

        # 如果能提取到新旧内容，生成 diff
        # 从 DB 读取新内容（generate_* 已内含写库）
        from app.models.work_model import Chapter

        db_chapter = db.query(Chapter).filter_by(
            work_id=work_id, chapter_number=chapter_number
        ).first()
        new_content_from_db = db_chapter.content if db_chapter else ""

        if old_content and new_content_from_db:
            diff = _build_diff(old_content, new_content_from_db)
            summary = _summarize_diff(diff)
            result["old_content"] = old_content
            result["new_content"] = new_content_from_db
            result["diff"] = diff
            result["summary"] = summary

            if emit_diff_event:
                self.emit("edit_chapter_diff", {
                    "diff": diff,
                    "summary": summary,
                    "old_content": old_content,
                    "new_content": new_content_from_db,
                    "chapter_number": chapter_number,
                })

        return result

    # ── 保留旧接口兼容（accept_edit 仍可从 dispatch 层调用） ──

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


def _extract_content_from_read(read_result: str) -> str:
    """从 read_chapter 工具返回的文本中提取正文内容"""
    marker_start = "--- 正文开始 ---"
    marker_end = "--- 正文结束 ---"
    start_idx = read_result.find(marker_start)
    end_idx = read_result.find(marker_end)
    if start_idx != -1 and end_idx != -1:
        return read_result[start_idx + len(marker_start):end_idx].strip()
    return ""


def _extract_content_from_generate(generate_result: str) -> str:
    """从 generate_* 返回文本中提取正文段落。"""
    marker = "--- 修改后正文 ---"
    idx = generate_result.find(marker)
    if idx == -1:
        return ""
    return generate_result[idx + len(marker):].strip()


import difflib


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
