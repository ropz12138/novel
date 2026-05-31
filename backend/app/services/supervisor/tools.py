"""SupervisorAgent 工具注册 — 查询工具 + 需求分析工具 + 状态机工具 + 派发工具

架构:
- 查询工具: Supervisor 直接使用（包含原有工具 + 从子 Agent 补充的工具）
- 需求分析工具: analyze_requirements, read_work_context, read_chat_history（原 RequirementsPlannerAgent 的工具）
- 状态机工具: update_task_status（维护 task_items 表中的任务状态）
- 派发工具: Supervisor 将任务描述传给子 Agent, 子 Agent 自己决定如何执行
  - dispatch_outline: 派发给 OutlineAgent (创建/编辑大纲)
  - dispatch_chapter: 派发给 ChapterAgent / EditChapterAgent (撰写新章 / 编辑正文，非只读查询)
  - dispatch_evaluation: 派发给 EvaluationAgent (章节质量评估)
"""

from __future__ import annotations

import logging
from json import dumps
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.supervisor.edit_chapter_tools import (
    grep_chapter_meta,
    query_chapter_meta,
)
from app.services.supervisor.edit_chapter_tools import (
    grep_in_chapter,
    query_characters_by_chapter,
    read_chapter,
)
from app.services.supervisor.outline_tools import (
    query_outline_related_chapters,
    read_outline,
)
from app.services.agent.chapter_tools import (
    query_chapter_outline,
    query_foreshadowing,
    query_previous_chapters,
)

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"


def _remap_top_level_task_ids(todolist: list) -> tuple[dict[str, str], list[list[str]]]:
    """Assign deterministic T1/T2 ids and remap depends_on references."""
    old_id_to_new: dict[str, str] = {}
    for idx, task in enumerate(todolist):
        new_id = f"T{idx + 1}"
        raw_id = str(getattr(task, "id", "") or "").strip()
        if raw_id:
            old_id_to_new[raw_id] = new_id
        old_id_to_new.setdefault(new_id, new_id)

    remapped_depends_on: list[list[str]] = []
    for task in todolist:
        deps = []
        for dep in getattr(task, "depends_on", []) or []:
            dep_text = str(dep).strip()
            if dep_text:
                deps.append(old_id_to_new.get(dep_text, dep_text))
        remapped_depends_on.append(deps)
    return old_id_to_new, remapped_depends_on


# ── Tool input schemas ──


class QueryCharactersInput(BaseModel):
    filters: dict = Field(
        default_factory=dict,
        description="过滤条件，支持 role_type, gender, name, current_status, "
                    "first_chapter__lte/gte, last_chapter__lte/gte, "
                    "字段名__contains（模糊搜索）",
    )


class QueryChaptersInput(BaseModel):
    filters: dict = Field(
        default_factory=dict,
        description="过滤条件，支持 chapter_number, chapter_number__lte/gte, "
                    "title__contains, status",
    )
    content_preview_length: int = Field(
        default=200,
        description="章节内容预览长度（字符数），0 表示返回完整内容",
    )


class GrepInput(BaseModel):
    keywords: list[str] = Field(description="搜索关键词列表，支持同时搜索多个关键词")
    scope: str = Field(default="all", description="搜索范围: all / characters / chapters")
    character_name: str | None = Field(default=None, description="可选：仅搜索指定角色名")
    chapter_start: int | None = Field(default=None, description="可选：起始章节号")
    chapter_end: int | None = Field(default=None, description="可选：结束章节号")
    chapter_number: int | None = Field(default=None, description="兼容字段：单章节号（等价于 start=end）")
    context_chars: int = Field(default=200, description="上下文字符数")


class DispatchOutlineInput(BaseModel):
    message: str = Field(description="任务描述：用户想要对大纲做什么，如「丰富大纲，增加女主角戏份」或「从零创建一个末日科幻故事」")


class DispatchChapterInput(BaseModel):
    instruction: str = Field(
        default="",
        description=(
            "撰写或修改正文的任务描述，如「写第一章」「修改第三章结尾」「根据评估建议优化对话」。"
            "不要用于只读查询（查元数据用 query_chapter_meta，查标题/预览用 query_chapters）。"
        ),
    )
    chapter_number: int | None = Field(
        default=None,
        description="章节号。撰写/修改时建议明确传入；不传时写新章场景由子 Agent 推断下一章序号",
    )


class DispatchEvaluationInput(BaseModel):
    chapter_number: int = Field(description="要评估的章节号")
    chapter_content: str = Field(
        default="",
        description="可选：要评估的正文草稿。不传时 EvaluationAgent 读取数据库中已保存的章节正文",
    )


class ReadRequirementsDocInput(BaseModel):
    pass


class UpdateRequirementsDocInput(BaseModel):
    content: str = Field(description="完整的需求文档内容（全量覆盖）")


class ReadWorkContextInput(BaseModel):
    pass


class ReadChatHistoryInput(BaseModel):
    limit: int = Field(default=10, description="读取最近几条消息")


class AnalyzeRequirementsInput(BaseModel):
    message: str = Field(description="用户的需求描述")
    work_context: str = Field(default="", description="作品上下文信息")
    history: str = Field(default="", description="历史对话")


class UpdateTaskStatusInput(BaseModel):
    task_item_id: str = Field(description="任务记录ID（task_items 表的主键）")
    status: str = Field(
        description="新状态，可选值: pending / in_progress / completed / skipped / failed",
    )
    result_summary: str = Field(default="", description="可选：执行结果摘要")


class UpdateTodolistReadinessInput(BaseModel):
    ready_to_execute: bool = Field(description="信息是否充分可执行。true=可执行，false=待澄清")


class EditTodolistInput(BaseModel):
    action: str = Field(description="操作类型：add / update / delete")
    task_id: str | None = Field(default=None, description="目标任务编号（update/delete 必填，如 T3）")
    task_description: str | None = Field(default=None, description="任务描述（add 必填；update 可选）")
    agent: str | None = Field(default=None, description="子 Agent：outline / chapter / evaluation（可选，add 默认自动推断）")
    instruction: str | None = Field(default=None, description="子 Agent 收到的指令（可选）")
    done_criteria: str | None = Field(default=None, description="完成标准（可选）")
    depends_on: str | None = Field(default=None, description="依赖的任务编号，逗号分隔（可选）")


class DispatchWritingExpertInput(BaseModel):
    problem_type: str = Field(
        description="问题类型：conflict_event/hook_design/pacing_fix/character_tension/dialogue_upgrade",
    )
    genre_tags: list[str] = Field(description="题材标签列表，例如 ['玄幻']、['都市', '悬疑']")
    constraints: list[str] = Field(
        default_factory=list,
        description="约束条件，例如 ['不死人', '轻喜', '第一人称']",
    )
    chapter_goal: str = Field(default="", description="章节目标，例如“制造主角与反派首次正面冲突”")
    chapter_number: int | None = Field(default=None, description="可选：目标章节号")
    count: int = Field(default=8, description="候选建议数量，默认 8")


# ── Helpers ──


def _get_db(config: RunnableConfig) -> Session:
    configurable = config.get("configurable", {})
    db = configurable.get("db")
    if db is None:
        raise ValueError("db Session 未在 configurable 中提供")
    return db


def _get_emit(config: RunnableConfig):
    configurable = config.get("configurable", {})
    return configurable.get("emit", lambda event, data: None)


def _store_memory(memories: dict[str, list[str]], agent_key: str, text: str) -> None:
    if agent_key not in memories:
        memories[agent_key] = []
    memories[agent_key].append(text)


def _get_user_id(config: RunnableConfig) -> str | None:
    configurable = config.get("configurable", {})
    return configurable.get("user_id")


def _get_session_id(config: RunnableConfig) -> str:
    session_id = (config or {}).get("configurable", {}).get("supervisor_session_id")
    if not session_id:
        raise ValueError("当前没有活跃的会话。")
    return str(session_id)


def _get_work_id(config: RunnableConfig) -> str:
    """从 config 中获取 work_id，支持从 session 中回退查找。"""
    work_id = str((config or {}).get("configurable", {}).get("work_id") or "")
    if work_id:
        return work_id
    configurable = (config or {}).get("configurable", {})
    session_id = configurable.get("supervisor_session_id")
    if session_id:
        db = configurable.get("db")
        if db:
            from app.models.agent_model import SupervisorSession
            session = db.query(SupervisorSession).filter_by(id=session_id).first()
            if session and session.work_id:
                return str(session.work_id)
    return ""


def _resolve_bound_work_id(
    config: RunnableConfig,
    db: Session,
    requested_work_id: str | None,
) -> tuple[str | None, str | None]:
    """Enforce supervisor session -> single work binding.

    Returns:
      (effective_work_id, error_message)
    """
    session_id = (config or {}).get("configurable", {}).get("supervisor_session_id")
    cfg_work_id = (config or {}).get("configurable", {}).get("work_id") or None

    from app.models.agent_model import SupervisorSession

    session = db.query(SupervisorSession).filter_by(id=session_id).first() if session_id else None
    bound_work_id = (session.work_id if session and session.work_id else None) or cfg_work_id
    if not bound_work_id:
        return requested_work_id, None

    if not requested_work_id:
        return bound_work_id, None

    if requested_work_id != bound_work_id:
        return None, (
            "业务规则校验未通过：会话与作品绑定不一致。"
            "为避免跨作品误操作，本次请求已拒绝。"
            "请使用当前会话继续操作，或开启新会话后再操作其他作品。"
        )

    return requested_work_id, None


def _format_characters(results: list[dict]) -> str:
    if not results:
        return "没有找到匹配的角色。"
    lines = []
    for c in results:
        parts = [f"【{c['name']}】{c['role_type']}"]
        for key in (
            "gender", "age", "appearance", "personality", "background", "skills",
            "current_status", "current_goal", "last_location", "first_chapter",
        ):
            if c.get(key):
                label_map = {
                    "gender": "性别", "age": "年龄", "personality": "性格",
                    "appearance": "外貌", "background": "背景", "skills": "技能",
                    "current_status": "状态", "current_goal": "目的",
                    "last_location": "位置", "first_chapter": "首次出场",
                }
                parts.append(f"{label_map[key]}：{c[key]}")
        lines.append("，".join(parts))
    return "\n".join(lines)


def _format_chapters(results: list[dict], *, content_preview_length: int = 200) -> str:
    if not results:
        return "没有找到匹配的章节。"
    lines = []
    for ch in results:
        content = ch.get("content", ch.get("content_preview", ""))
        if content_preview_length > 0 and len(content) > content_preview_length:
            content = content[:content_preview_length] + f"...（共{len(content)}字）"
        word_count = len(ch.get("content", "").replace("\n", "").replace(" ", ""))
        lines.append(f"第{ch['chapter_number']}章 {ch['title']}（{ch['status']}，{word_count}字）：{content}")
    return "\n".join(lines)


def _format_grep(results: list[dict], keyword: str) -> str:
    if not results:
        return f"未找到包含「{keyword}」的内容。"
    lines = []
    for r in results:
        if r["source"] == "character":
            lines.append(f"[角色 {r['character_name']}·{r['field']}] {r['snippet']}")
        else:
            lines.append(f"[第{r['chapter_number']}章 {r['chapter_title']}] {r['snippet']}")
    return "\n".join(lines)


def _dispatch_tool_result(
    *,
    ok: bool,
    status: str,
    tool: str,
    message: str,
    action: str = "",
    work_id: str | None = None,
    chapter_number: int | None = None,
    warnings: list[str] | None = None,
    error: dict | None = None,
    payload: dict | None = None,
) -> str:
    """Return a structured dispatch result for the deterministic todo harness."""
    return dumps(
        {
            "ok": ok,
            "status": status,
            "tool": tool,
            "action": action,
            "work_id": work_id,
            "chapter_number": chapter_number,
            "message": message,
            "warnings": warnings or [],
            "error": error,
            "payload": payload or {},
        },
        ensure_ascii=False,
    )


# ── 查询工具（同步，统筹 Agent 直接使用） ──


@tool(args_schema=QueryCharactersInput)
def query_characters(filters: dict, config: RunnableConfig, work_id: str | None = None) -> str:
    """结构化查询角色卡。支持按角色类型、性别、名字、状态等字段过滤。
    在回答用户关于角色的问题之前，先用此工具查询角色信息。"""
    from app.services.character_service import CharacterService

    db = _get_db(config)
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err
    if not work_id:
        return "当前会话尚未绑定作品。"
    results = CharacterService.query_data(work_id=work_id, target="characters", filters=filters, db=db, user_id=_get_user_id(config))
    return _format_characters(results)


@tool(args_schema=QueryChaptersInput)
def query_chapters(filters: dict, content_preview_length: int, config: RunnableConfig, work_id: str | None = None) -> str:
    """结构化查询章节列表与基本信息（章节号、标题、状态、字数、正文预览）。

    不包含章节元数据（摘要、关键情节、伏笔、角色状态变化、事实索引、一致性状态）。
    查元数据请用 query_chapter_meta；在元数据中搜关键词请用 grep_chapter_meta。
    支持按章节号范围、标题模糊搜索、状态过滤。默认只返回内容预览以节省 token。
    """
    from app.services.character_service import CharacterService

    db = _get_db(config)
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err
    if not work_id:
        return "当前会话尚未绑定作品。"
    results = CharacterService.query_data(work_id=work_id, target="chapters", filters=filters, db=db, user_id=_get_user_id(config))
    return _format_chapters(results, content_preview_length=content_preview_length)


class CountChapterWordsInput(BaseModel):
    chapter_number: int = Field(description="要计算字数的章节号")
    work_id: str | None = Field(default=None, description="作品 ID（默认使用当前会话绑定的作品）")


@tool(args_schema=CountChapterWordsInput)
def count_chapter_words(chapter_number: int, config: RunnableConfig, work_id: str | None = None) -> str:
    """计算指定章节正文的字数（去除空格和换行后的纯文字数）。"""
    from app.models.work_model import Chapter

    db = _get_db(config)
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err
    if not work_id:
        return "当前会话尚未绑定作品。"

    chapter = db.query(Chapter).filter_by(
        work_id=work_id, chapter_number=chapter_number
    ).first()
    if not chapter:
        return f"第{chapter_number}章不存在。"

    content = chapter.content or ""
    word_count = len(content.replace("\n", "").replace(" ", ""))

    return f"第{chapter_number}章「{chapter.title}」字数：{word_count} 字"


@tool(args_schema=GrepInput)
def grep(
    keywords: list[str],
    scope: str,
    context_chars: int,
    config: RunnableConfig,
    work_id: str | None = None,
    character_name: str | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    chapter_number: int | None = None,
) -> str:
    """在角色设定和/或章节正文中搜索关键词（不搜索章节元数据字段）。

    查元数据中的关键词请用 grep_chapter_meta。支持一次传入多个关键词，返回上下文片段。
    """
    from app.services.character_service import CharacterService

    db = _get_db(config)
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err
    if not work_id:
        return "当前会话尚未绑定作品。"

    all_results = []
    seen_snippets = set()
    if chapter_number is not None:
        chapter_start = chapter_number
        chapter_end = chapter_number

    for kw in keywords:
        results = CharacterService.grep(
            work_id=work_id, keyword=kw, scope=scope,
            context_chars=context_chars, db=db,
            character_name=character_name,
            chapter_number=chapter_number,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            user_id=_get_user_id(config),
        )
        for r in results:
            snippet_key = (r.get("source"), r.get("character_name") or r.get("chapter_number"), r.get("field"), kw)
            if snippet_key not in seen_snippets:
                r["_keyword"] = kw
                all_results.append(r)
                seen_snippets.add(snippet_key)

    if not all_results:
        return f"未找到包含 {keywords} 的内容。"

    # 按关键词分组格式化
    grouped: dict[str, list] = {}
    for r in all_results:
        kw = r.pop("_keyword", "")
        grouped.setdefault(kw, []).append(r)

    lines = []
    for kw, items in grouped.items():
        lines.append(f"── 关键词「{kw}」──")
        for r in items:
            if r["source"] == "character":
                lines.append(f"  [角色 {r['character_name']}·{r['field']}] {r['snippet']}")
            else:
                lines.append(f"  [第{r['chapter_number']}章 {r['chapter_title']}] {r['snippet']}")
    return "\n".join(lines)


# ── 需求分析工具（原 RequirementsPlannerAgent 的工具） ──


@tool(args_schema=ReadWorkContextInput)
def read_work_context(config: RunnableConfig, work_id: str | None = None) -> str:
    """读取作品的基本信息，用于理解当前写作进度和上下文。"""
    from app.models.work_model import Work

    db = _get_db(config)
    emit = _get_emit(config)
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err
    if not work_id:
        return "当前会话尚未绑定作品。"

    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    outline = work.outline_tree or {}
    story = outline.get("story", {})
    timeline = outline.get("timeline", [])

    context = "\n".join([
        f"标题: {work.title}",
        f"类型: {story.get('genre', '')}",
        f"卷: {story.get('volume', '')}",
        f"时间线节点数: {len(timeline)}",
    ])

    emit("requirements_context_read", {"work_id": work_id})
    return context


@tool(args_schema=ReadChatHistoryInput)
def read_chat_history(limit: int, config: RunnableConfig, session_id: str | None = None) -> str:
    """读取当前会话的最近对话历史，用于理解用户的前后文需求。"""
    from app.services import message_service

    db = _get_db(config)
    emit = _get_emit(config)
    session_id = session_id or _get_session_id(config)

    messages = message_service.get_messages_by_session(db, session_id)
    recent = messages[-limit:] if len(messages) > limit else messages

    if not recent:
        return "暂无对话历史。"

    parts = []
    for m in recent:
        parts.append(f"[{m.role}] {m.content}")

    emit("requirements_history_read", {"count": len(recent)})
    return "\n".join(parts)


@tool(args_schema=ReadRequirementsDocInput)
def read_requirements_doc(config: RunnableConfig) -> str:
    """读取当前作品的用户需求文档，全量返回内容，禁止截断。"""
    from app.models.work_model import Work

    db = _get_db(config)
    work_id = _get_work_id(config)
    if not work_id:
        return "错误：当前会话未绑定作品，无法读取需求文档。"

    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"错误：作品 {work_id} 不存在。"

    if not work.requirements_doc:
        return "（暂无需求记录）"

    return work.requirements_doc


@tool(args_schema=UpdateRequirementsDocInput)
def update_requirements_doc(content: str, config: RunnableConfig) -> str:
    """当用户明确提出写作需求、偏好、风格要求、约束条件等长期有效的指导信息时，调用此工具更新需求文档。全量覆盖写入。"""
    from app.models.work_model import Work

    db = _get_db(config)
    emit = _get_emit(config)
    work_id = _get_work_id(config)
    if not work_id:
        return "错误：当前会话未绑定作品，无法更新需求文档。"

    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"错误：作品 {work_id} 不存在。"

    work.requirements_doc = content
    db.commit()

    emit("requirements_doc_updated", {"work_id": work_id})
    return "需求文档已更新。"


async def _analyze_requirements_coroutine(
    message: str,
    work_context: str = "",
    history: str = "",
    config: RunnableConfig = None,
) -> str:
    """分析用户需求，生成结构化的需求分析和任务清单，并持久化到 task_items 表。"""
    from langchain_core.prompts import PromptTemplate

    from app.models.task_item_model import TaskItem
    from app.services.supervisor.sub_agent_base import get_llm

    class TaskItemResult(BaseModel):
        id: str = Field(default="T1", description="任务ID")
        task: str = Field(description="任务描述")
        owner: str = Field(default="supervisor", description="负责人")
        task_type: str = Field(default="", description="任务类型")
        dispatch_tool: str = Field(default="", description="建议执行工具")
        instruction: str = Field(default="", description="传给执行工具的任务意图")
        depends_on: list[str] = Field(default_factory=list, description="依赖任务ID")
        status: str = Field(default="pending", description="状态")
        done_criteria: str = Field(default="", description="完成判定标准")

    class RequirementsAnalysisResult(BaseModel):
        intent_summary: str = Field(default="", description="一句话目标")
        requirements: list[str] = Field(default_factory=list, description="明确需求列表")
        constraints: list[str] = Field(default_factory=list, description="约束列表")
        assumptions: list[str] = Field(default_factory=list, description="假设列表")
        questions: list[str] = Field(default_factory=list, description="需要用户确认的问题")
        todolist: list[TaskItemResult] = Field(default_factory=list, description="任务清单")
        ready_to_execute: bool = Field(default=False, description="信息是否充分可执行")

    db = _get_db(config)
    emit = _get_emit(config)
    session_id = (config or {}).get("configurable", {}).get("supervisor_session_id")

    template = (PROMPT_DIR / "requirements_planner.txt").read_text(encoding="utf-8")
    prompt = PromptTemplate.from_template(template)
    llm = get_llm(temperature=0.2, streaming=False)
    structured_llm = llm.with_structured_output(
        RequirementsAnalysisResult,
        method="function_calling",
    )

    chain = prompt | structured_llm

    result = await chain.ainvoke({
        "user_message": message,
        "work_context": work_context or "（未绑定作品）",
        "history": history or "（无历史对话）",
    })

    questions = result.questions if result.questions else []
    todolist = result.todolist if result.todolist else []

    # owner -> dispatch_tool 推断映射
    OWNER_DISPATCH_MAP = {
        "outline_agent": "dispatch_outline",
        "chapter_agent": "dispatch_chapter",
        "evaluation_agent": "dispatch_evaluation",
    }
    TASK_TYPE_DISPATCH_MAP = {
        "outline": "dispatch_outline",
        "chapter_write": "dispatch_chapter",
        "chapter_edit": "dispatch_chapter",
        "metadata": "dispatch_chapter",
        "evaluation": "dispatch_evaluation",
    }
    DISPATCH_OWNER_MAP = {
        "dispatch_outline": "outline_agent",
        "dispatch_chapter": "chapter_agent",
        "dispatch_evaluation": "evaluation_agent",
    }

    def infer_dispatch_tool(t: TaskItemResult) -> str:
        if t.dispatch_tool and t.dispatch_tool != "none":
            return t.dispatch_tool
        if OWNER_DISPATCH_MAP.get(t.owner):
            return OWNER_DISPATCH_MAP[t.owner]
        if TASK_TYPE_DISPATCH_MAP.get(t.task_type):
            return TASK_TYPE_DISPATCH_MAP[t.task_type]

        text = f"{t.task or ''} {t.instruction or ''} {message or ''}"
        if any(keyword in text for keyword in ("评估", "评价", "审稿", "打分")):
            return "dispatch_evaluation"
        if any(keyword in text for keyword in ("章节", "正文", "写第", "撰写", "续写", "改写", "编辑")):
            return "dispatch_chapter"
        if any(keyword in text for keyword in ("大纲", "角色", "主线", "支线", "伏笔", "设定")):
            return "dispatch_outline"
        return ""

    # 清理同一 session 中的旧 todolist（含子任务），防止重复调用导致 task_id 冲突
    if session_id and todolist:
        from app.services.supervisor.todo_harness import cleanup_session_todolist
        cleanup_session_todolist(session_id=session_id, db=db)

    # 持久化任务到 task_items 表。任务编号由程序统一分配，LLM 返回的 id 仅用于依赖重映射。
    old_id_to_new, remapped_depends_on_by_index = _remap_top_level_task_ids(todolist)

    persisted_tasks = []
    for idx, t in enumerate(todolist):
        import uuid
        # 兼容：LLM 未返回 dispatch_tool 或误填 owner=user/supervisor 时，从任务类型和文本推断
        effective_dispatch_tool = infer_dispatch_tool(t)
        if not effective_dispatch_tool:
            effective_dispatch_tool = "none"
        effective_owner = t.owner
        if effective_dispatch_tool != "none" and effective_owner in ("user", "supervisor", "", None):
            effective_owner = DISPATCH_OWNER_MAP.get(effective_dispatch_tool, effective_owner)
        # 兼容：LLM 未返回 instruction 时使用 task 描述
        effective_instruction = t.instruction or t.task or message
        remapped_depends_on = remapped_depends_on_by_index[idx]

        task_item = TaskItem(
            id=str(uuid.uuid4()),
            session_id=session_id or "",
            parent_id=None,
            depth=0,
            agent_scope="supervisor",
            task_id=f"T{idx + 1}",
            task_description=t.task,
            owner=effective_owner,
            status=t.status or "pending",
            depends_on=",".join(remapped_depends_on) if remapped_depends_on else "",
            done_criteria=t.done_criteria or "",
            sort_order=idx,
            task_type=t.task_type or "",
            dispatch_tool=effective_dispatch_tool,
            instruction=effective_instruction,
        )
        db.add(task_item)
        persisted_tasks.append({
            "db_id": task_item.id,
            "task_id": task_item.task_id,
            "task": task_item.task_description,
            "owner": task_item.owner,
            "status": task_item.status,
            "parent_id": "",
            "depth": 0,
            "agent_scope": "supervisor",
            "depends_on": remapped_depends_on,
            "done_criteria": task_item.done_criteria,
            "task_type": task_item.task_type,
            "dispatch_tool": task_item.dispatch_tool,
            "instruction": task_item.instruction,
        })

    # 将 ready_to_execute 持久化到 session（与 task_items 在同一个事务中）
    if todolist or result.intent_summary:
        if session_id:
            from app.models.agent_model import SupervisorSession
            session_obj = db.query(SupervisorSession).filter_by(id=session_id).first()
            if session_obj:
                session_obj.ready_to_execute = result.ready_to_execute

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    if todolist or result.intent_summary:
        emit("todolist_generated", {
            "intent_summary": result.intent_summary or "",
            "todolist": persisted_tasks,
            "ready_to_execute": result.ready_to_execute,
        })

    if questions:
        return f"需求分析完成。发现 {len(questions)} 个需要澄清的问题。\n" + "\n".join(f"- {q}" for q in questions)

    task_lines = []
    for pt in persisted_tasks:
        task_lines.append(
            f"- [{pt['task_id']}] {pt['task']} (db_id={pt['db_id']}, 状态={pt['status']}, 派发={pt['dispatch_tool']})"
        )
    return (
        f"需求已明确，生成了 {len(todolist)} 条任务。\n"
        + "\n".join(task_lines)
        + "\n\n请使用 execute_todo_task(task_item_id=<task_id 或 db_id>) 依次执行任务。"
    )


analyze_requirements = StructuredTool.from_function(
    func=None,
    coroutine=_analyze_requirements_coroutine,
    name="analyze_requirements",
    description="分析用户需求，生成结构化的需求分析、澄清问题和任务清单。任务清单会持久化到数据库，可通过 update_task_status 更新状态。",
    args_schema=AnalyzeRequirementsInput,
)


# ── 状态机工具 ──


@tool(args_schema=UpdateTaskStatusInput)
def update_task_status(task_item_id: str, status: str, result_summary: str, config: RunnableConfig) -> str:
    """更新任务状态。合法状态: pending / in_progress / completed / skipped / failed。"""
    from app.models.task_item_model import TaskItem

    VALID_STATUSES = {"pending", "in_progress", "completed", "skipped", "failed"}
    TERMINAL_STATUSES = {"completed", "skipped", "failed"}
    if status not in VALID_STATUSES:
        return f"无效状态：{status}。合法值为：{', '.join(sorted(VALID_STATUSES))}"

    db = _get_db(config)
    emit = _get_emit(config)

    task = db.query(TaskItem).filter_by(id=task_item_id).first()
    if not task:
        return f"任务记录 {task_item_id} 不存在。"

    old_status = task.status
    if old_status in TERMINAL_STATUSES and status != old_status:
        return (
            f"任务 {task.task_id} 当前已是终态 {old_status}，不可改为 {status}。"
            "如果任务执行失败，请向用户反馈失败原因，或重新分析需求生成新的 todolist；"
            "不要重开、跳过或绕过已结束的任务。"
        )

    task.status = status
    if result_summary:
        task.result_summary = result_summary

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    emit("task_status_updated", {
        "task_item_id": task_item_id,
        "task_id": task.task_id,
        "old_status": old_status,
        "new_status": status,
        "result_summary": result_summary or task.result_summary,
    })

    return f"任务 {task.task_id}（{task.task_description}）状态已更新：{old_status} -> {status}"


@tool(args_schema=UpdateTodolistReadinessInput)
def update_todolist_readiness(ready_to_execute: bool, config: RunnableConfig, session_id: str | None = None) -> str:
    """更新任务清单的'可执行'状态。当需求信息已充分时设为 true，当需要进一步澄清时设为 false。"""
    from app.models.agent_model import SupervisorSession

    db = _get_db(config)
    emit = _get_emit(config)
    session_id = session_id or _get_session_id(config)

    session = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not session:
        return f"会话 {session_id} 不存在。"

    old_value = session.ready_to_execute
    session.ready_to_execute = ready_to_execute

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    label = "可执行" if ready_to_execute else "待澄清"
    old_label = "可执行" if old_value else "待澄清"
    emit("todolist_readiness_updated", {
        "session_id": session_id,
        "ready_to_execute": ready_to_execute,
    })

    return f"任务清单状态已更新：{old_label} -> {label}"


@tool(args_schema=EditTodolistInput)
def edit_todolist(
    action: str,
    config: RunnableConfig,
    task_id: str | None = None,
    task_description: str | None = None,
    agent: str | None = None,
    instruction: str | None = None,
    done_criteria: str | None = None,
    depends_on: str | None = None,
) -> str:
    """对后续（pending）顶层任务进行增/改/删操作。用于执行过程中根据子 Agent 反馈动态调整后续计划。"""
    from app.models.task_item_model import TaskItem
    import uuid as _uuid

    VALID_ACTIONS = {"add", "update", "delete"}
    if action not in VALID_ACTIONS:
        return f"无效操作：{action}。合法值为：{', '.join(sorted(VALID_ACTIONS))}"

    AGENT_TOOL_MAP = {
        "outline": "dispatch_outline",
        "chapter": "dispatch_chapter",
        "evaluation": "dispatch_evaluation",
    }
    _dispatch_owner_map = {
        "dispatch_outline": "outline_agent",
        "dispatch_chapter": "chapter_agent",
        "dispatch_evaluation": "evaluation_agent",
    }
    if agent and agent not in AGENT_TOOL_MAP:
        return f"无效 agent：{agent}。合法值为：{', '.join(AGENT_TOOL_MAP.keys())}"

    db = _get_db(config)
    emit = _get_emit(config)
    session_id = _get_session_id(config)

    # Query all tasks for this session
    all_session_tasks = (
        db.query(TaskItem)
        .filter_by(session_id=session_id)
        .order_by(TaskItem.sort_order)
        .all()
    )
    # Top-level tasks for iteration
    top_tasks = [t for t in all_session_tasks if t.depth == 0]

    def _find_by_task_id(tid: str) -> TaskItem | None:
        for t in all_session_tasks:
            if t.task_id == tid:
                return t
        return None

    def _next_task_id() -> str:
        max_num = 0
        for t in top_tasks:
            try:
                num = int(t.task_id.replace("T", ""))
                if num > max_num:
                    max_num = num
            except ValueError:
                continue
        return f"T{max_num + 1}"

    def _validate_depends(dep_str: str) -> str | None:
        """Validate depends_on references; return error msg or None."""
        if not dep_str:
            return None
        existing_ids = {t.task_id for t in top_tasks}
        for ref in dep_str.split(","):
            ref = ref.strip()
            if ref and ref not in existing_ids:
                return f"依赖的任务 {ref} 不存在于当前 todolist 中。"
        return None

    # ── ADD ──
    if action == "add":
        if not task_description:
            return "添加任务需要提供 task_description。"

        if depends_on:
            err = _validate_depends(depends_on)
            if err:
                return err

        new_id = _next_task_id()
        dispatch_tool = AGENT_TOOL_MAP.get(agent, "") if agent else ""
        owner = _dispatch_owner_map.get(dispatch_tool, "supervisor") if dispatch_tool else "supervisor"

        task_item = TaskItem(
            id=str(_uuid.uuid4()),
            session_id=session_id or "",
            parent_id=None,
            depth=0,
            agent_scope="supervisor",
            task_id=new_id,
            task_description=task_description,
            owner=owner,
            status="pending",
            depends_on=depends_on or "",
            done_criteria=done_criteria or "",
            sort_order=len(top_tasks),
            task_type="",
            dispatch_tool=dispatch_tool or "none",
            instruction=instruction or task_description,
        )
        db.add(task_item)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        emit("todolist_task_added", {
            "task_id": new_id,
            "db_id": task_item.id,
            "task_description": task_description,
            "owner": owner,
            "dispatch_tool": dispatch_tool,
            "instruction": instruction or task_description,
            "depends_on": depends_on or "",
            "done_criteria": done_criteria or "",
            "sort_order": task_item.sort_order,
        })

        return f"已添加任务 {new_id}：{task_description}"

    # ── UPDATE ──
    if action == "update":
        if not task_id:
            return "更新任务需要提供 task_id。"

        task = _find_by_task_id(task_id)
        if not task:
            return f"任务 {task_id} 不存在。"

        if task.depth != 0:
            return f"任务 {task_id} 是子任务，不支持直接编辑。仅可编辑顶层任务。"

        if task.status != "pending":
            return f"任务 {task_id} 当前状态为 {task.status}，不可编辑。仅 pending 状态的任务可修改。"

        if depends_on:
            err = _validate_depends(depends_on)
            if err:
                return err

        if task_description is not None:
            task.task_description = task_description
        if instruction is not None:
            task.instruction = instruction
        if done_criteria is not None:
            task.done_criteria = done_criteria
        if depends_on is not None:
            task.depends_on = depends_on
        if agent is not None:
            task.dispatch_tool = AGENT_TOOL_MAP[agent]
            task.owner = _dispatch_owner_map.get(task.dispatch_tool, task.owner)

        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        emit("todolist_task_edited", {
            "task_id": task.task_id,
            "db_id": task.id,
            "task_description": task.task_description,
            "owner": task.owner,
            "dispatch_tool": task.dispatch_tool,
            "instruction": task.instruction,
            "depends_on": task.depends_on,
            "done_criteria": task.done_criteria,
        })

        return f"已更新任务 {task_id}。"

    # ── DELETE ──
    if action == "delete":
        if not task_id:
            return "删除任务需要提供 task_id。"

        task = _find_by_task_id(task_id)
        if not task:
            return f"任务 {task_id} 不存在。"

        if task.depth != 0:
            return f"任务 {task_id} 是子任务，不支持直接删除。仅可删除顶层任务。"

        if task.status != "pending":
            return f"任务 {task_id} 当前状态为 {task.status}，不可删除。仅 pending 状态的任务可删除。"

        # Check if any other pending task depends on this one
        dependents = [
            t for t in top_tasks
            if t.task_id != task_id
            and t.depends_on
            and task_id in [d.strip() for d in t.depends_on.split(",")]
        ]
        if dependents:
            dep_ids = ", ".join(t.task_id for t in dependents)
            return f"任务 {task_id} 被以下任务依赖，无法删除：{dep_ids}。请先移除依赖关系或删除依赖方。"

        emit("todolist_task_deleted", {
            "task_id": task.task_id,
            "db_id": task.id,
        })

        db.delete(task)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        return f"已删除任务 {task_id}。"

    return f"未知操作：{action}"


# ── Todo Execution Harness 工具 ──


class ExecuteTodoTaskInput(BaseModel):
    task_item_id: str = Field(
        description="要执行的任务编号（如 T1、T2）或数据库ID（db_id）。"
        "analyze_requirements 返回结果中包含此信息。"
    )
    agent: str | None = Field(
        default=None,
        description="可选：显式指定子 Agent，取值 outline / chapter / evaluation；不传则按任务自动推断。",
    )


class ReadTodolistInput(BaseModel):
    pass  # session_id 从 config 自动获取，LLM 无需传参


async def _execute_todo_task_coroutine(
    task_item_id: str,
    config: RunnableConfig,
    agent: str | None = None,
) -> str:
    """执行 todolist 中的一条任务"""
    from app.services.supervisor.todo_harness import execute_todo_task

    db = _get_db(config)
    emit = _get_emit(config)
    return await execute_todo_task(
        task_item_id=task_item_id,
        db=db,
        emit=emit,
        config=config,
        agent=agent,
    )


execute_todo_task_tool = StructuredTool.from_function(
    func=None,
    coroutine=_execute_todo_task_coroutine,
    name="execute_todo_task",
    description=(
        "执行 todolist 中的一条任务。该工具会自动维护任务状态："
        "pending -> in_progress -> completed/failed，并路由到对应子 Agent。"
        "执行 todolist 任务时必须使用本工具；Supervisor 不再暴露 dispatch_* 入口工具。"
        "该工具会自动校验依赖、更新状态并发射事件，无需手动调用 update_task_status。"
        "参数 task_item_id 可以是任务编号（如 T1、T2，推荐）或数据库ID（如 abc-def-...）。"
        "可选参数 agent 可显式指定 outline / chapter / evaluation；不传时按任务自动推断。"
        "analyze_requirements 返回值中包含了每个任务的编号，直接使用即可。"
    ),
    args_schema=ExecuteTodoTaskInput,
)


@tool(args_schema=ReadTodolistInput)
def read_todolist(config: RunnableConfig) -> str:
    """读取当前会话的任务清单（todolist），返回所有任务及其状态、依赖关系和执行信息。无需传参，自动获取当前会话。"""
    import json
    from app.models.agent_model import SupervisorSession
    from app.models.task_item_model import TaskItem
    from app.services.supervisor.todo_harness import serialize_task_item

    db = _get_db(config)
    emit = _get_emit(config)
    session_id = (config or {}).get("configurable", {}).get("supervisor_session_id")

    if not session_id:
        return "当前没有活跃的会话。"

    session = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not session:
        return f"会话 {session_id} 不存在。"

    tasks = (
        db.query(TaskItem)
        .filter_by(session_id=session_id)
        .order_by(TaskItem.depth.asc(), TaskItem.sort_order.asc(), TaskItem.created_at.asc())
        .all()
    )

    serialized = [serialize_task_item(t) for t in tasks]

    status_counts = {}
    for t in tasks:
        status_counts[t.status] = status_counts.get(t.status, 0) + 1

    summary = {
        "session_id": session_id,
        "ready_to_execute": session.ready_to_execute,
        "total_tasks": len(tasks),
        "status_counts": status_counts,
        "tasks": serialized,
    }

    return json.dumps(summary, ensure_ascii=False, indent=2)


# ── 派发工具（异步，统筹 Agent 传递意图给子 Agent） ──


def _guard_direct_dispatch_todolist(tool_name: str, config: RunnableConfig, db: Session) -> str | None:
    """有待执行或失败的顶层 todolist 时，禁止 Supervisor 绕过状态机 dispatch。"""
    configurable = (config or {}).get("configurable", {})
    if configurable.get("todo_harness_bypass"):
        return None

    session_id = configurable.get("supervisor_session_id")
    if not session_id:
        return None

    from app.models.task_item_model import TaskItem

    blocked_tasks = (
        db.query(TaskItem)
        .filter_by(session_id=session_id)
        .filter(TaskItem.status.in_(["pending", "in_progress", "failed"]))
        .order_by(TaskItem.sort_order)
        .all()
    )
    blocked = next((t for t in blocked_tasks if getattr(t, "parent_id", None) in (None, "")), None)
    if not blocked:
        return None

    if blocked.status == "failed":
        return (
            f"工具策略拦截：当前会话存在失败任务 {blocked.task_id}"
            f"（{blocked.task_description}）。"
            "请先向用户反馈失败原因，或重新调用 analyze_requirements 生成新的 todolist，"
            f"不要直接调用 {tool_name}。"
        )

    if blocked.status == "in_progress":
        return (
            f"工具策略拦截：当前会话存在执行中任务 {blocked.task_id}"
            f"（{blocked.task_description}）。"
            "请等待 execute_todo_task 返回结果，"
            f"不要并行直接调用 {tool_name}。"
        )

    return (
        f"工具策略拦截：当前会话仍有待执行任务 {blocked.task_id}"
        f"（{blocked.task_description}）。"
        f"请调用 execute_todo_task(task_item_id=\"{blocked.task_id}\")，"
        f"不要直接调用 {tool_name}。"
    )


async def _dispatch_outline_coroutine(message: str, config: RunnableConfig, work_id: str | None = None) -> str:
    """派发大纲任务 — 子 Agent 自行决定创建还是编辑"""
    from app.models.agent_model import SupervisorSession
    from app.services.supervisor.outline_agent import OutlineAgent

    emit = _get_emit(config)
    db = _get_db(config)
    guard_message = _guard_direct_dispatch_todolist("dispatch_outline", config, db)
    if guard_message:
        return guard_message
    configurable = config.get("configurable", {})
    db_lock = config.get("configurable", {}).get("db_lock")
    session_id = configurable.get("supervisor_session_id")
    session = None
    if session_id:
        session = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not work_id and session and session.work_id:
        work_id = session.work_id

    # 保护：若调用方传入 work_id，与会话绑定作品不一致，则拒绝跨作品操作
    if session and session.work_id and work_id and work_id != session.work_id:
        return (
            "无法执行：当前操作目标与会话绑定作品不一致。"
            "请使用当前会话继续操作，或开启新会话后再操作其他作品。"
        )

    agent = OutlineAgent(emit=emit, user_id=configurable.get("user_id"))

    memories: dict[str, list[str]] = configurable.get("sub_agent_memories", {})

    async def _run_locked(coro):
        """如果有 db_lock（threading.Lock）则直接执行（锁已传给内层 graph）。"""
        return await coro

    if not work_id:
        # 无 work_id → 创建新大纲（直接执行，不需要确认）
        result = await _run_locked(
            agent.create_outline(
                idea=message,
                tags=[],
                db=db,
                db_lock=db_lock,
                base_configurable=configurable,
            )
        )
        if result.get("error"):
            if session:
                session.status = "error"
                session.stage = "done"
            return f"创建大纲失败：{result['error']}"
        created_work_id = result.get("work_id")
        if created_work_id:
            # 关键修复：创建成功后将 work_id 绑定到当前 supervisor session，
            # 否则作品详情页按 work_id 查询时看不到这次对话。
            from app.models.message_model import Message

            if session_id:
                sess = session or db.query(SupervisorSession).filter_by(id=session_id).first()
                if sess:
                    sess.work_id = created_work_id
                db.query(Message).filter(
                    Message.session_id == session_id,
                    Message.work_id.is_(None),
                ).update({"work_id": created_work_id}, synchronize_session=False)
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
            logger.info(
                "dispatch_outline create_done session_id=%s work_id=%s",
                session_id,
                created_work_id,
            )
        _store_memory(memories, "outline", f"创建大纲：{result.get('title', '')}")
        return (
            f"大纲创建成功。作品「{result.get('title', '')}」"
        )
    else:
        # 有 work_id → 编辑已有大纲
        auto_mode = config.get("configurable", {}).get("auto_mode", False)

        result = await _run_locked(
            agent.edit_outline(
                work_id=work_id, message=message, history=memories.get("outline", []), db=db,
                auto_mode=auto_mode, db_lock=db_lock, base_configurable=configurable,
            )
        )
        if result.get("error"):
            return f"编辑大纲失败：{result.get('message', result.get('error', '未知错误'))}"

        _store_memory(memories, "outline", f"编辑大纲 work_id={work_id}：{result.get('message', '')}")

        if auto_mode:
            return result.get("message", "大纲编辑已完成。")

        # 默认模式：设置 waiting 状态，等待用户确认
        outline_summary = result.get("outline_summary", {})
        character_summary = result.get("character_summary", {})
        ops = result.get("operations", [])

        if session_id:
            sess = session or db.query(SupervisorSession).filter_by(id=session_id).first()
            if sess:
                sess.active_child = {
                    "type": "edit_outline",
                    "work_id": work_id,
                    "task_item_id": configurable.get("current_task_item_id"),
                }
                sess.status = "waiting"
                sess.stage = "executing"
                configurable["supervisor_stop_after_tool"] = True
                logger.info(
                    "dispatch_outline edit_waiting stop_after_tool session_id=%s work_id=%s ops=%s",
                    session_id,
                    work_id,
                    len(ops),
                )

        return (
            f"大纲变更建议已生成"
            f"（大纲 +{outline_summary.get('total_added', 0)}/~{outline_summary.get('total_modified', 0)}/-{outline_summary.get('total_removed', 0)}"
            f"，角色 +{character_summary.get('total_added', 0)}/~{character_summary.get('total_modified', 0)}/-{character_summary.get('total_removed', 0)}"
            f"）。"
            f"执行了 {len(ops)} 项操作。请等待用户确认。"
        )


async def _dispatch_chapter_coroutine(
    instruction: str,
    chapter_number: int | None,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """派发章节任务 — 统一由 ChapterAgent 处理新写和编辑"""
    from app.models.work_model import Chapter
    from app.services.chapter_outline_sync_service import ChapterOutlineSyncService
    from app.services.supervisor.chapter_agent import ChapterAgent

    emit = _get_emit(config)
    db = _get_db(config)
    guard_message = _guard_direct_dispatch_todolist("dispatch_chapter", config, db)
    if guard_message:
        return _dispatch_tool_result(
            ok=False,
            status="rejected",
            tool="dispatch_chapter",
            action="chapter_dispatch",
            work_id=work_id,
            chapter_number=chapter_number,
            message=guard_message,
            error={"code": "TODO_STATE_BLOCKED", "detail": guard_message},
        )
    db_lock = config.get("configurable", {}).get("db_lock")
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return _dispatch_tool_result(
            ok=False,
            status="rejected",
            tool="dispatch_chapter",
            action="chapter_dispatch",
            work_id=work_id,
            chapter_number=chapter_number,
            message=err,
            error={"code": "WORK_BINDING_MISMATCH", "detail": err},
        )
    if not work_id:
        message = "当前会话尚未绑定作品。"
        return _dispatch_tool_result(
            ok=False,
            status="rejected",
            tool="dispatch_chapter",
            action="chapter_dispatch",
            chapter_number=chapter_number,
            message=message,
            error={"code": "WORK_NOT_BOUND", "detail": message},
        )

    auto_mode = config.get("configurable", {}).get("auto_mode", False)

    # 判断是新写还是编辑
    is_new_chapter = False
    if chapter_number is not None:
        existing = db.query(Chapter).filter_by(
            work_id=work_id, chapter_number=chapter_number
        ).first()
        if existing and existing.content:
            is_new_chapter = False
        else:
            is_new_chapter = True
    else:
        # 未指定章节号 → 新写下一章
        is_new_chapter = True

    # 新写章节时校验顺序约束
    if is_new_chapter:
        max_chapter = db.query(Chapter).filter_by(work_id=work_id).order_by(Chapter.chapter_number.desc()).first()
        expected_next = (max_chapter.chapter_number + 1) if max_chapter else 1

        if chapter_number is None:
            actual_chapter = expected_next
        else:
            actual_chapter = chapter_number

        if actual_chapter != expected_next:
            message = (
                "业务规则校验未通过：新增章节必须严格顺序。"
                f"当前已存在至第{expected_next - 1}章，因此只能新增第{expected_next}章，"
                f"不能新增第{actual_chapter}章。本次请求已拒绝。"
                f"请改为“写第{expected_next}章”或“写下一章”。"
            )
            return _dispatch_tool_result(
                ok=False,
                status="rejected",
                tool="dispatch_chapter",
                action="chapter_write",
                work_id=work_id,
                chapter_number=actual_chapter,
                message=message,
                error={"code": "CHAPTER_SEQUENCE_VIOLATION", "detail": message},
                payload={"expected_next_chapter": expected_next},
            )

        chapter_number = actual_chapter

        # 拼接上下文包
        write_context = ChapterOutlineSyncService.build_write_context(
            db,
            work_id=work_id,
            chapter_number=actual_chapter,
            user_instruction=instruction or "",
        )
        enriched_instruction = (
            f"{instruction or ''}\n\n"
            f"{write_context}\n\n"
            "输出要求：正文完成后保持与上述上下文一致，避免角色状态与时间线冲突。"
        )
    else:
        enriched_instruction = instruction or f"修改第{chapter_number}章"

    # 统一调用 ChapterAgent
    agent = ChapterAgent(emit=emit)

    try:
        result = await agent.run(
            work_id=work_id,
            chapter_number=chapter_number,
            user_message=enriched_instruction,
            db=db,
            is_new_chapter=is_new_chapter,
            auto_mode=auto_mode,
            db_lock=db_lock,
            base_configurable=config.get("configurable", {}),
        )
    except Exception as exc:
        db.rollback()
        task_label = "写作" if is_new_chapter else "编辑"
        import traceback
        tb_str = traceback.format_exception(type(exc), exc, exc.__traceback__)
        logger.error("dispatch_chapter %s failed:\n%s", task_label, "".join(tb_str))
        message = f"第{chapter_number}章{task_label}失败：{exc!r}"
        return _dispatch_tool_result(
            ok=False,
            status="failed",
            tool="dispatch_chapter",
            action="chapter_write" if is_new_chapter else "chapter_edit",
            work_id=work_id,
            chapter_number=chapter_number,
            message=message,
            error={"code": "CHAPTER_AGENT_ERROR", "detail": repr(exc)},
        )

    # ── 新写章节的后续处理 ──
    if is_new_chapter:
        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        if not chapter:
            message = f"第{chapter_number}章写作完成，但未找到章节记录。"
            return _dispatch_tool_result(
                ok=False,
                status="failed",
                tool="dispatch_chapter",
                action="chapter_write",
                work_id=work_id,
                chapter_number=chapter_number,
                message=message,
                error={"code": "CHAPTER_RECORD_MISSING", "detail": message},
            )

        from app.models.work_model import Work
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            message = f"第{chapter_number}章写作完成，但未找到作品记录。"
            return _dispatch_tool_result(
                ok=False,
                status="failed",
                tool="dispatch_chapter",
                action="chapter_write",
                work_id=work_id,
                chapter_number=chapter_number,
                message=message,
                error={"code": "WORK_RECORD_MISSING", "detail": message},
            )

        metadata_row = None
        try:
            from app.models.work_model import ChapterMetadata

            metadata_row = (
                db.query(ChapterMetadata)
                .filter_by(work_id=work_id, chapter_number=chapter_number)
                .first()
            )
            if not metadata_row:
                metadata_row = await ChapterOutlineSyncService.generate_and_persist(
                    db,
                    work=work,
                    chapter=chapter,
                )
                db.commit()
        except Exception as exc:
            db.rollback()
            logger.exception(
                "dispatch_chapter metadata sync skipped after saved chapter=%s: %s",
                chapter_number,
                exc,
            )

        if metadata_row:
            emit("chapter_metadata_generated", {
                "chapter_number": chapter_number,
                "summary": metadata_row.summary,
                "key_plot_points": metadata_row.key_plot_points,
                "outline_links": metadata_row.outline_links,
                "involved_characters": metadata_row.involved_characters,
                "foreshadows": metadata_row.foreshadows,
                "facts": metadata_row.facts,
                "updated_at": metadata_row.updated_at.isoformat() if metadata_row.updated_at else None,
            })

        memories: dict[str, list[str]] = config.get("configurable", {}).get("sub_agent_memories", {})
        _store_memory(memories, "chapter", f"写第{chapter_number}章完成")

        metadata_note = "已同步章节元数据。" if metadata_row else "章节元数据稍后可重新同步。"
        message = f"第{chapter_number}章写作完成。{metadata_note}"
        return _dispatch_tool_result(
            ok=True,
            status="completed",
            tool="dispatch_chapter",
            action="chapter_write",
            work_id=work_id,
            chapter_number=chapter_number,
            message=message,
            warnings=[] if metadata_row else [metadata_note],
            payload={
                "created": True,
                "metadata_synced": bool(metadata_row),
            },
        )

    # ── 编辑章节的后续处理 ──
    summary = result.get("summary", {})

    if auto_mode:
        from app.models.work_model import Chapter as _Ch
        old_chapter = db.query(_Ch).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        new_content = old_chapter.content if old_chapter else ""
        old_content = result.get("old_content", "")

        from app.services.supervisor.chapter_agent import _build_diff, _summarize_diff
        if old_content and new_content and old_content != new_content:
            diff = _build_diff(old_content, new_content)
            summary = _summarize_diff(diff)
        else:
            diff = []
            summary = summary or {}

        emit("edit_chapter_auto_applied", {
            "chapter_number": chapter_number,
            "title": (old_chapter.title if old_chapter else "") or f"第{chapter_number}章",
            "word_count": len((new_content or "").replace("\n", "").replace(" ", "")),
            "summary": summary,
            "diff": diff,
            "new_content": new_content,
        })
        memories: dict[str, list[str]] = config.get("configurable", {}).get("sub_agent_memories", {})
        _store_memory(memories, "chapter", f"自动编辑第{chapter_number}章：+{summary.get('lines_added', 0)}行/-{summary.get('lines_removed', 0)}行")
        message = (
            f"第{chapter_number}章修改已完成"
            f"（+{summary.get('lines_added', 0)}行 / -{summary.get('lines_removed', 0)}行）。"
        )
        return _dispatch_tool_result(
            ok=True,
            status="completed",
            tool="dispatch_chapter",
            action="chapter_edit",
            work_id=work_id,
            chapter_number=chapter_number,
            message=message,
            payload={
                "auto_applied": True,
                "summary": summary,
            },
        )

    # 默认模式：设置 waiting 状态，等待用户确认
    from app.models.agent_model import SupervisorSession
    session_id = config.get("configurable", {}).get("supervisor_session_id")
    if session_id:
        sess = db.query(SupervisorSession).filter_by(id=session_id).first()
        if sess:
            sess.active_child = {
                "type": "edit_chapter",
                "work_id": work_id,
                "chapter_number": chapter_number,
                "old_content": result.get("old_content", ""),
                "new_content": result.get("new_content", ""),
                "task_item_id": config.get("configurable", {}).get("current_task_item_id"),
            }
            sess.status = "waiting"
            sess.stage = "executing"
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise

    if summary:
        memories: dict[str, list[str]] = config.get("configurable", {}).get("sub_agent_memories", {})
        _store_memory(memories, "chapter", f"编辑第{chapter_number}章：+{summary.get('lines_added', 0)}行/-{summary.get('lines_removed', 0)}行")
        message = (
            f"第{chapter_number}章修改已完成"
            f"（+{summary.get('lines_added', 0)}行 / -{summary.get('lines_removed', 0)}行）。"
            f"请等待用户确认是否接受修改。"
        )
        return _dispatch_tool_result(
            ok=True,
            status="waiting",
            tool="dispatch_chapter",
            action="chapter_edit",
            work_id=work_id,
            chapter_number=chapter_number,
            message=message,
            payload={
                "auto_applied": False,
                "summary": summary,
            },
        )

    message = (
        f"第{chapter_number}章修改已完成。"
        f"{result.get('message', '')}"
    )
    return _dispatch_tool_result(
        ok=True,
        status="waiting",
        tool="dispatch_chapter",
        action="chapter_edit",
        work_id=work_id,
        chapter_number=chapter_number,
        message=message,
        payload={"auto_applied": False},
    )



async def _dispatch_evaluation_coroutine(
    chapter_number: int,
    chapter_content: str = "",
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """派发章节评估任务给 EvaluationAgent。"""
    from app.services.evaluation_agent import EvaluationAgent

    emit = _get_emit(config)
    db = _get_db(config)
    guard_message = _guard_direct_dispatch_todolist("dispatch_evaluation", config, db)
    if guard_message:
        return guard_message
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err
    if not work_id:
        return "当前会话尚未绑定作品。"

    emit("stage_start", {"stage": "evaluation", "label": f"评估第{chapter_number}章"})

    memories: dict[str, list[str]] = config.get("configurable", {}).get("sub_agent_memories", {})
    eval_history = memories.get("evaluation", [])

    agent = EvaluationAgent()
    try:
        title, editor_text, reader_text, sync_text = await agent.evaluate_chapter(
            db=db,
            work_id=work_id,
            chapter_number=chapter_number,
            chapter_content_override=chapter_content,
            history=eval_history,
            base_configurable=config.get("configurable", {}),
        )
    except Exception as exc:
        logger.exception("dispatch_evaluation failed: %s", exc)
        return f"评估失败：{exc}"

    # 存入子 agent 记忆
    summary = f"第{chapter_number}章「{title}」编辑评估：{editor_text}；读者评估：{reader_text}；同步性：{sync_text}"
    _store_memory(memories, "evaluation", summary)

    emit("evaluation_done", {
        "chapter_number": chapter_number,
        "chapter_title": title,
        "editor": editor_text,
        "reader": reader_text,
        "sync": sync_text,
    })

    return (
        f"第{chapter_number}章「{title}」评估完成。\n"
        f"【编辑视角】{editor_text}\n"
        f"【读者视角】{reader_text}\n"
        f"【同步性】{sync_text}"
    )


async def _dispatch_writing_expert_coroutine(
    problem_type: str,
    genre_tags: list[str],
    constraints: list[str] | None = None,
    chapter_goal: str = "",
    chapter_number: int | None = None,
    count: int = 8,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """派发写作专家微咨询任务。"""
    from app.services.supervisor.writing_expert_agent import WritingExpertAgent

    emit = _get_emit(config)
    db = _get_db(config)
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err
    if not work_id:
        return "当前会话尚未绑定作品。"

    memories: dict[str, list[str]] = config.get("configurable", {}).get("sub_agent_memories", {})

    agent = WritingExpertAgent(emit=emit)
    try:
        result = await agent.advise(
            db=db,
            problem_type=problem_type,
            genre_tags=genre_tags,
            constraints=constraints or [],
            chapter_goal=chapter_goal,
            chapter_number=chapter_number,
            count=count,
            history=memories.get("writing_expert", []),
        )
    except ValueError as exc:
        return f"写作专家建议生成失败：{exc}"
    except Exception as exc:
        logger.exception("dispatch_writing_expert failed: %s", exc)
        return f"写作专家建议生成失败：{exc}"

    _store_memory(memories, "writing_expert", f"写作建议({problem_type})：{str(result.get('recommended_pick', {}))}")

    recommended = result.get("recommended_pick", {})
    options = result.get("options", [])
    summary = (
        f"写作专家已返回 {len(options)} 条建议。"
        f"首选方案：{recommended.get('event_name', '（无）')}。"
        f"可直接用于章节改写的指令如下：\n"
        f"{result.get('apply_prompt_for_chapter_agent', '')}"
    )
    # 附带结构化结果，便于后续链路从文本里提取。
    return summary + "\n\n[writing_expert_payload]\n" + dumps(result, ensure_ascii=False)


# ── 构建 StructuredTool（派发工具） ──

dispatch_outline = StructuredTool.from_function(
    func=None,
    coroutine=_dispatch_outline_coroutine,
    name="dispatch_outline",
    description=(
        "派发大纲任务给大纲子 Agent。"
        "当用户想要创建新大纲或修改已有大纲时使用。"
        "传入任务描述，子 Agent 会自行决定如何执行（创建新大纲或编辑已有大纲的节点、角色等）。"
        "作品绑定由系统自动处理。"
    ),
    args_schema=DispatchOutlineInput,
)

dispatch_chapter = StructuredTool.from_function(
    func=None,
    coroutine=_dispatch_chapter_coroutine,
    name="dispatch_chapter",
    description=(
        "【兼容工具，不推荐】派发章节撰写或编辑任务给 ChapterAgent（执行型，不是只读查询）。"
        "todolist 中的章节任务必须使用 execute_todo_task，禁止直接调用本工具。"
        "仅在没有活跃 todolist 且需手动触发章节子 Agent 的非清单场景下使用。"
        "适用：撰写新章、修改已有章节正文。"
        "不适用：仅查看章节元数据 → query_chapter_meta / grep_chapter_meta；"
        "仅查看标题/状态/正文预览 → query_chapters；正文内搜关键词 → grep。"
        "传入 instruction 描述用户意图；章节号由 ChapterAgent 在工具调用时自行传入。"
    ),
    args_schema=DispatchChapterInput,
)


dispatch_evaluation = StructuredTool.from_function(
    func=None,
    coroutine=_dispatch_evaluation_coroutine,
    name="dispatch_evaluation",
    description=(
        "派发章节评估任务给 EvaluationAgent。"
        "当用户要求评价、评估、打分、指出章节问题、从编辑或读者视角审稿时使用。"
        "可评估数据库中已保存的章节正文，也可传入临时正文草稿。"
        "评估返回的问题和改进建议会用于后续章节优化。"
    ),
    args_schema=DispatchEvaluationInput,
)

dispatch_writing_expert = StructuredTool.from_function(
    func=None,
    coroutine=_dispatch_writing_expert_coroutine,
    name="dispatch_writing_expert",
    description=(
        "派发写作专家微咨询任务。"
        "用于章节写作中需要具体建议时（如冲突事件、章末钩子、节奏修复、人物张力、对话升级）。"
        "该工具不做全局研究，只返回当前问题可直接落地的候选方案与章节改写指令。"
    ),
    args_schema=DispatchWritingExpertInput,
)


# ── 导出所有工具列表 ──

ALL_TOOLS = [
    query_characters,
    query_chapters,
    count_chapter_words,
    query_chapter_meta,
    grep_chapter_meta,
    grep,
    # 从子 Agent 补充的查询工具
    read_outline,
    query_outline_related_chapters,
    read_chapter,
    query_characters_by_chapter,
    grep_in_chapter,
    query_chapter_outline,
    query_previous_chapters,
    query_foreshadowing,
    # 需求分析工具
    read_work_context,
    read_chat_history,
    analyze_requirements,
    # 需求文档工具
    read_requirements_doc,
    update_requirements_doc,
    # 状态机工具
    update_task_status,
    update_todolist_readiness,
    edit_todolist,
    # Todo Execution Harness 工具
    execute_todo_task_tool,
    read_todolist,
]
