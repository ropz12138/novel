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

from app.services.supervisor.edit_chapter_tools import EDIT_CHAPTER_TOOLS as _EDIT_TOOLS
from app.services.agent.chapter_tools import CHAPTER_TOOLS as _WRITE_TOOLS
from app.services.supervisor.sub_agent_base import (
    chunk_to_ai_message,
    get_llm,
)

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"


# ── 合并工具集 ──

# 去重合并：EDIT_CHAPTER_TOOLS 和 CHAPTER_TOOLS
_SEEN = set()
CHAPTER_AGENT_TOOLS = []
for _t in (*_WRITE_TOOLS, *_EDIT_TOOLS):
    if _t.name not in _SEEN:
        _SEEN.add(_t.name)
        CHAPTER_AGENT_TOOLS.append(_t)

# 追加 supervisor 层的字数统计工具
from app.services.supervisor.tools import count_chapter_words
if count_chapter_words.name not in _SEEN:
    CHAPTER_AGENT_TOOLS.append(count_chapter_words)


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
) -> str:
    """构建 ChapterAgent 的 system prompt"""
    template = (PROMPT_DIR / "chapter_agent_system.txt").read_text(encoding="utf-8")
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


async def _chapter_agent_node(state: ChapterAgentState) -> dict:
    """LLM 节点"""
    llm = get_llm(temperature=0.7)
    llm_with_tools = llm.bind_tools(CHAPTER_AGENT_TOOLS)

    messages = state.get("messages", [])

    has_system = any(isinstance(m, SystemMessage) for m in messages)
    if not has_system:
        system_prompt = state.get("_system_prompt", "")
        full_messages = [SystemMessage(content=system_prompt)] + messages
    else:
        full_messages = messages

    aggregated = None
    async for chunk in llm_with_tools.astream(full_messages):
        aggregated = chunk if aggregated is None else aggregated + chunk

    if aggregated is None:
        raise RuntimeError("ChapterAgent LLM 未返回任何流式分片")

    response = chunk_to_ai_message(aggregated)
    return {"messages": [response]}


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

    def _build_graph(self):
        """构建 LangGraph StateGraph"""
        graph = StateGraph(ChapterAgentState)
        graph.add_node("agent", _chapter_agent_node)
        graph.add_node("tools", ToolNode(CHAPTER_AGENT_TOOLS))

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

        graph = self._build_graph()

        configurable = dict(base_configurable or {})
        configurable.update({
            "db": db,
            "emit": self.emit,
            "db_lock": db_lock,
            "work_id": work_id,
            "chapter_number": chapter_number,
        })
        logger.info("ChapterAgent.run configurable keys: %s", list(configurable.keys()))
        for k, v in configurable.items():
            if isinstance(v, bool):
                logger.warning("ChapterAgent.run configurable[%r] is bool: %r", k, v)
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

        final_state = None
        async for event in graph.astream(initial_state, config=config):
            for node_name, node_output in event.items():
                if node_name == "tools":
                    if not isinstance(node_output, dict):
                        logger.warning("Unexpected node_output type from 'tools': %s", type(node_output))
                        continue
                    tool_msgs = node_output.get("messages", [])
                    for tm in tool_msgs:
                        content = tm.content if hasattr(tm, "content") else str(tm)
                        self.emit("tool_result", {
                            "tool_name": getattr(tm, "name", "unknown"),
                            "tool_call_id": getattr(tm, "tool_call_id", ""),
                            "content": str(content)[:500],
                        })
                    continue
                if not isinstance(node_output, dict):
                    logger.warning(
                        "ChapterAgent.run ignored non-dict node_output from %r: %s",
                        node_name,
                        type(node_output),
                    )
                    continue
                if node_name == "agent":
                    final_state = node_output
                elif final_state is None:
                    final_state = node_output

        # 提取最终回复
        final_messages = final_state.get("messages", []) if isinstance(final_state, dict) else []
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
            old_content = ""
            for msg in final_messages:
                if hasattr(msg, "name") and msg.name == "read_chapter":
                    old_content = _extract_content_from_read(msg.content)

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
