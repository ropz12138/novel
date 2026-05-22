"""RequirementsPlannerAgent 工具集

需求澄清与任务规划子 Agent 的工具。
"""

from __future__ import annotations

import logging

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Tool input schemas ──


class ReadWorkContextInput(BaseModel):
    work_id: str = Field(description="作品ID")


class ReadChatHistoryInput(BaseModel):
    session_id: str = Field(description="会话ID")
    limit: int = Field(default=10, description="读取最近几条消息")


class AnalyzeRequirementsInput(BaseModel):
    message: str = Field(description="用户的需求描述")
    work_context: str = Field(default="", description="作品上下文信息")
    history: str = Field(default="", description="历史对话")


# ── Helpers ──


def _get_db(config: RunnableConfig):
    from sqlalchemy.orm import Session
    configurable = config.get("configurable", {})
    db = configurable.get("db")
    if db is None:
        raise ValueError("db Session 未在 configurable 中提供")
    return db


def _get_emit(config: RunnableConfig):
    configurable = config.get("configurable", {})
    return configurable.get("emit", lambda event, data: None)


# ── 工具实现 ──


@tool(args_schema=ReadWorkContextInput)
def read_work_context(work_id: str, config: RunnableConfig) -> str:
    """读取作品的基本信息，用于理解当前写作进度和上下文。"""
    from app.models.work_model import Work

    db = _get_db(config)
    emit = _get_emit(config)

    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    outline = work.outline_tree or {}
    story = outline.get("story", {})
    timeline = outline.get("timeline", [])

    context = "\n".join([
        f"work_id: {work.id}",
        f"标题: {work.title}",
        f"类型: {story.get('genre', '')}",
        f"卷: {story.get('volume', '')}",
        f"时间线节点数: {len(timeline)}",
    ])

    emit("requirements_context_read", {"work_id": work_id})
    return context


@tool(args_schema=ReadChatHistoryInput)
def read_chat_history(session_id: str, limit: int, config: RunnableConfig) -> str:
    """读取当前会话的最近对话历史，用于理解用户的前后文需求。"""
    from app.services import message_service

    db = _get_db(config)
    emit = _get_emit(config)

    messages = message_service.get_messages_by_session(db, session_id)
    recent = messages[-limit:] if len(messages) > limit else messages

    if not recent:
        return "暂无对话历史。"

    parts = []
    for m in recent:
        parts.append(f"[{m.role}] {m.content[:200]}")

    emit("requirements_history_read", {"count": len(recent)})
    return "\n".join(parts)


async def _analyze_requirements_coroutine(
    message: str,
    work_context: str = "",
    history: str = "",
    config: RunnableConfig = None,
) -> str:
    """分析用户需求，生成结构化的需求分析和任务清单。"""
    from pathlib import Path

    from langchain_core.prompts import PromptTemplate
    from pydantic import BaseModel, Field

    from app.services.supervisor.sub_agent_base import get_llm

    class TaskItem(BaseModel):
        id: str = Field(default="T1", description="任务ID")
        task: str = Field(description="任务描述")
        owner: str = Field(default="supervisor", description="负责人")
        depends_on: list[str] = Field(default_factory=list, description="依赖任务ID")
        status: str = Field(default="pending", description="状态")
        done_criteria: str = Field(default="", description="完成判定标准")

    class RequirementsAnalysisResult(BaseModel):
        intent_summary: str = Field(default="", description="一句话目标")
        requirements: list[str] = Field(default_factory=list, description="明确需求列表")
        constraints: list[str] = Field(default_factory=list, description="约束列表")
        assumptions: list[str] = Field(default_factory=list, description="假设列表")
        questions: list[str] = Field(default_factory=list, description="需要用户确认的问题")
        todolist: list[TaskItem] = Field(default_factory=list, description="任务清单")
        ready_to_execute: bool = Field(default=False, description="信息是否充分可执行")

    emit = _get_emit(config)

    prompt_dir = Path(__file__).resolve().parent.parent / "prompt_templates"
    template = (prompt_dir / "requirements_planner.txt").read_text(encoding="utf-8")
    prompt = PromptTemplate.from_template(template)
    llm = get_llm(temperature=0.2, streaming=False)
    structured_llm = llm.with_structured_output(RequirementsAnalysisResult)

    chain = prompt | structured_llm

    result = await chain.ainvoke({
        "user_message": message,
        "work_context": work_context or "（未绑定作品）",
        "history": history or "（无历史对话）",
    })

    questions = result.questions if result.questions else []
    todolist = result.todolist if result.todolist else []

    if todolist or result.intent_summary:
        emit("todolist_generated", {
            "intent_summary": result.intent_summary or "",
            "todolist": [t.model_dump() for t in todolist],
            "ready_to_execute": result.ready_to_execute,
        })

    if questions:
        return f"需求分析完成。发现 {len(questions)} 个需要澄清的问题。\n" + "\n".join(f"- {q}" for q in questions[:5])

    return f"需求已明确，生成了 {len(todolist)} 条任务。\n" + "\n".join(f"- {t.task}" for t in todolist[:8])


from langchain_core.tools import StructuredTool

analyze_requirements = StructuredTool.from_function(
    func=None,
    coroutine=_analyze_requirements_coroutine,
    name="analyze_requirements",
    description="分析用户需求，生成结构化的需求分析、澄清问题和任务清单。",
    args_schema=AnalyzeRequirementsInput,
)


# ── 导出工具列表 ──

REQUIREMENTS_PLANNER_TOOLS = [
    read_work_context,
    read_chat_history,
    analyze_requirements,
]
