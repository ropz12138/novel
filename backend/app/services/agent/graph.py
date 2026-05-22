"""Chapter writing agent — 基于 LangGraph StateGraph + Tool-Calling 的章节撰写子 Agent

改造自原来的硬编码流水线，现在 LLM 自主选择工具：
- 查询大纲、前文、角色、伏笔
- 生成章节正文
- 保存章节
- 更新角色状态

保留 auto_mode 机制：auto_mode=True 时全部自动执行，auto_mode=False 时有确认点。
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
from app.models.agent_model import AgentState
from app.services.agent.chapter_tools import CHAPTER_TOOLS
from app.services.supervisor.sub_agent_base import (
    chunk_to_ai_message,
    get_llm,
    stream_text_delta,
)

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompt_templates"


# ── 状态定义 ──


class ChapterAgentState(MessagesState):
    """ChapterAgent 在 LangGraph StateGraph 中传递的状态"""

    work_id: str
    chapter_number: int
    user_instruction: str


# ── System Prompt ──


def _build_chapter_system_prompt(
    work_id: str,
    chapter_number: int,
    user_instruction: str,
    auto_mode: bool,
) -> str:
    """构建 ChapterAgent 的 system prompt"""
    template = (PROMPT_DIR / "chapter_agent_system.txt").read_text(encoding="utf-8")
    mode_desc = "自动模式：所有操作直接执行，不需要等待确认。" if auto_mode else "交互模式：完成关键步骤后可能需要等待用户确认。"
    return template.format(
        work_id=work_id,
        chapter_number=chapter_number,
        user_instruction=user_instruction,
        mode_description=mode_desc,
    )


# ── Agent Node ──


async def _chapter_agent_node(state: ChapterAgentState) -> dict:
    """LLM 节点：接收 messages，流式输出，返回 AIMessage。

    system prompt 只在首次调用时由 start() 注入到初始消息中，
    后续轮次直接使用 state 中的 messages。
    """
    llm = get_llm(temperature=0.7)
    llm_with_tools = llm.bind_tools(CHAPTER_TOOLS)

    messages = state.get("messages", [])

    # system prompt 已在初始消息中注入，无需重复添加
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


# ── ChapterAgentGraph 类 ──


class ChapterAgentGraph:
    """章节撰写 Agent — 使用 LangGraph StateGraph 编排 LLM 和工具调用"""

    def __init__(
        self,
        work_id: str,
        chapter_number: int,
        db: Session,
        emit,
        *,
        auto_mode: bool = False,
        db_lock: object | None = None,
    ):
        self.work_id = work_id
        self.chapter_number = chapter_number
        self.db = db
        self.emit = emit
        self.auto_mode = auto_mode
        self.db_lock = db_lock

    def _build_graph(self):
        """构建 LangGraph StateGraph"""
        graph = StateGraph(ChapterAgentState)
        graph.add_node("agent", _chapter_agent_node)
        graph.add_node("tools", ToolNode(CHAPTER_TOOLS))

        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
        graph.add_edge("tools", "agent")

        return graph.compile()

    async def start(self, instruction: str = "") -> AgentState:
        """启动章节写作任务。

        在 auto_mode 下：LLM 自主编排工具完成写作全流程。
        在非 auto_mode 下：LLM 同样自主编排，但可暂停等待确认。
        """
        self.emit("stage_start", {"stage": "chapter_write", "label": f"写第{self.chapter_number}章"})

        agent_record = self._ensure_agent_record()
        agent_record.user_instruction = instruction
        agent_record.stage = "running"
        agent_record.status = "running"
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        system_prompt = _build_chapter_system_prompt(
            work_id=self.work_id,
            chapter_number=self.chapter_number,
            user_instruction=instruction,
            auto_mode=self.auto_mode,
        )

        graph = self._build_graph()

        config = {
            "configurable": {
                "db": self.db,
                "emit": self.emit,
                "db_lock": self.db_lock,
                "work_id": self.work_id,
                "chapter_number": self.chapter_number,
            },
            "recursion_limit": 30,
        }

        initial_state = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=instruction or f"写第{self.chapter_number}章"),
            ],
            "work_id": self.work_id,
            "chapter_number": self.chapter_number,
            "user_instruction": instruction,
            "_system_prompt": system_prompt,
        }

        try:
            final_state = None
            async for event in graph.astream(initial_state, config=config):
                for node_name, node_output in event.items():
                    if node_name == "tools":
                        tool_msgs = node_output.get("messages", [])
                        for tm in tool_msgs:
                            content = tm.content if hasattr(tm, "content") else str(tm)
                            text = str(content)
                            # 仅给子 Agent 的内部校验反馈，不直接透传给前端用户。
                            # 例如 n+1 章节顺序校验失败，应该用于驱动 Agent 改写调用策略，
                            # 而不是作为用户可见错误气泡。
                            if (
                                "章节创建必须严格按 n+1 顺序" in text
                                or "无法解析 work_id，无法执行 n+1 章节校验" in text
                            ):
                                continue
                            self.emit("tool_result", {"content": text[:500]})
                final_state = node_output

            # 提取最终回复
            final_messages = final_state.get("messages", []) if final_state else []
            assistant_content = ""
            for msg in reversed(final_messages):
                if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                    assistant_content = msg.content
                    break

            agent_record.stage = "done"
            agent_record.status = "completed"
            self.db.commit()

            self.emit("done", {"message": assistant_content})
            return agent_record

        except Exception as exc:
            logger.exception("ChapterAgentGraph.start failed: %s", exc)
            self.db.rollback()
            agent_record.stage = "error"
            agent_record.status = "error"
            self.db.commit()
            return agent_record

    async def resume(self, action: str, instruction: str = "") -> AgentState:
        """恢复执行（保留兼容接口）。"""
        agent_record = self.db.query(AgentState).filter_by(
            work_id=self.work_id, chapter_number=self.chapter_number
        ).first()
        if not agent_record:
            raise ValueError("Agent state not found")

        if action in ("reject", "guide"):
            # 重新执行
            self.emit("stage_start", {"stage": "chapter_write", "label": f"重写第{self.chapter_number}章"})
            return await self.start(instruction=instruction or "用户不满意，请重新构思并撰写")

        return agent_record

    def _ensure_agent_record(self) -> AgentState:
        """创建或获取 AgentState DB 记录"""
        agent_record = self.db.query(AgentState).filter_by(
            work_id=self.work_id, chapter_number=self.chapter_number
        ).first()
        if not agent_record:
            agent_record = AgentState(
                work_id=self.work_id,
                chapter_number=self.chapter_number,
            )
            self.db.add(agent_record)
        return agent_record
