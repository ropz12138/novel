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


# ── Tool input schemas ──


class QueryCharactersInput(BaseModel):
    work_id: str = Field(description="作品ID")
    filters: dict = Field(
        default_factory=dict,
        description="过滤条件，支持 role_type, gender, name, current_status, "
                    "first_chapter__lte/gte, last_chapter__lte/gte, "
                    "字段名__contains（模糊搜索）",
    )


class QueryChaptersInput(BaseModel):
    work_id: str = Field(description="作品ID")
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
    work_id: str = Field(description="作品ID")
    keywords: list[str] = Field(description="搜索关键词列表，支持同时搜索多个关键词")
    scope: str = Field(default="all", description="搜索范围: all / characters / chapters")
    character_name: str | None = Field(default=None, description="可选：仅搜索指定角色名")
    chapter_start: int | None = Field(default=None, description="可选：起始章节号")
    chapter_end: int | None = Field(default=None, description="可选：结束章节号")
    chapter_number: int | None = Field(default=None, description="兼容字段：单章节号（等价于 start=end）")
    context_chars: int = Field(default=200, description="上下文字符数")


class DispatchOutlineInput(BaseModel):
    message: str = Field(description="任务描述：用户想要对大纲做什么，如「丰富大纲，增加女主角戏份」或「从零创建一个末日科幻故事」")
    work_id: str | None = Field(default=None, description="作品ID。已有作品时传入，不传则视为创建新大纲")


class DispatchChapterInput(BaseModel):
    work_id: str = Field(description="作品ID")
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
    work_id: str = Field(description="作品ID")
    chapter_number: int = Field(description="要评估的章节号")
    chapter_content: str = Field(
        default="",
        description="可选：要评估的正文草稿。不传时 EvaluationAgent 读取数据库中已保存的章节正文",
    )


class ReadWorkContextInput(BaseModel):
    work_id: str = Field(description="作品ID")


class ReadChatHistoryInput(BaseModel):
    session_id: str = Field(description="会话ID")
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
    session_id: str = Field(description="当前会话ID（supervisor_sessions 表的主键）")
    ready_to_execute: bool = Field(description="信息是否充分可执行。true=可执行，false=待澄清")


class DispatchWritingExpertInput(BaseModel):
    work_id: str = Field(description="作品ID")
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
    if not session_id:
        return requested_work_id, None

    from app.models.agent_model import SupervisorSession

    session = db.query(SupervisorSession).filter_by(id=session_id).first()
    if not session or not session.work_id:
        return requested_work_id, None

    if requested_work_id is None:
        return session.work_id, None

    if requested_work_id != session.work_id:
        return None, (
            "业务规则校验未通过：会话与作品绑定不一致。"
            f"当前会话绑定作品为 {session.work_id}，但你传入的是 {requested_work_id}。"
            "为避免跨作品误操作，本次请求已拒绝。"
            "请改为使用当前会话绑定的 work_id，或开启新会话后再操作其他作品。"
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


# ── 查询工具（同步，统筹 Agent 直接使用） ──


@tool(args_schema=QueryCharactersInput)
def query_characters(work_id: str, filters: dict, config: RunnableConfig) -> str:
    """结构化查询角色卡。支持按角色类型、性别、名字、状态等字段过滤。
    在回答用户关于角色的问题之前，先用此工具查询角色信息。"""
    from app.services.character_service import CharacterService

    db = _get_db(config)
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err
    results = CharacterService.query_data(work_id=work_id, target="characters", filters=filters, db=db, user_id=_get_user_id(config))
    return _format_characters(results)


@tool(args_schema=QueryChaptersInput)
def query_chapters(work_id: str, filters: dict, content_preview_length: int, config: RunnableConfig) -> str:
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
    results = CharacterService.query_data(work_id=work_id, target="chapters", filters=filters, db=db, user_id=_get_user_id(config))
    return _format_chapters(results, content_preview_length=content_preview_length)


@tool(args_schema=GrepInput)
def grep(
    work_id: str,
    keywords: list[str],
    scope: str,
    context_chars: int,
    config: RunnableConfig,
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
    """分析用户需求，生成结构化的需求分析和任务清单，并持久化到 task_items 表。"""
    from langchain_core.prompts import PromptTemplate

    from app.models.task_item_model import TaskItem
    from app.services.supervisor.sub_agent_base import get_llm

    class TaskItemResult(BaseModel):
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

    # 持久化任务到 task_items 表
    persisted_tasks = []
    for idx, t in enumerate(todolist):
        import uuid
        task_item = TaskItem(
            id=str(uuid.uuid4()),
            session_id=session_id or "",
            task_id=t.id or f"T{idx + 1}",
            task_description=t.task,
            owner=t.owner,
            status=t.status or "pending",
            depends_on=",".join(t.depends_on) if t.depends_on else "",
            done_criteria=t.done_criteria or "",
            sort_order=idx,
        )
        db.add(task_item)
        persisted_tasks.append({
            "db_id": task_item.id,
            "task_id": task_item.task_id,
            "task": task_item.task_description,
            "owner": task_item.owner,
            "status": task_item.status,
            "depends_on": t.depends_on,
            "done_criteria": task_item.done_criteria,
        })

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    if todolist or result.intent_summary:
        # 将 ready_to_execute 持久化到 session
        if session_id:
            from app.models.agent_model import SupervisorSession
            session_obj = db.query(SupervisorSession).filter_by(id=session_id).first()
            if session_obj:
                session_obj.ready_to_execute = result.ready_to_execute

        emit("todolist_generated", {
            "intent_summary": result.intent_summary or "",
            "todolist": persisted_tasks,
            "ready_to_execute": result.ready_to_execute,
        })

    if questions:
        return f"需求分析完成。发现 {len(questions)} 个需要澄清的问题。\n" + "\n".join(f"- {q}" for q in questions[:5])

    return f"需求已明确，生成了 {len(todolist)} 条任务。\n" + "\n".join(f"- {t.task}" for t in todolist[:8])


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
    import uuid

    from app.models.task_item_model import TaskItem

    VALID_STATUSES = {"pending", "in_progress", "completed", "skipped", "failed"}
    if status not in VALID_STATUSES:
        return f"无效状态：{status}。合法值为：{', '.join(sorted(VALID_STATUSES))}"

    db = _get_db(config)
    emit = _get_emit(config)

    task = db.query(TaskItem).filter_by(id=task_item_id).first()
    if not task:
        return f"任务记录 {task_item_id} 不存在。"

    old_status = task.status
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

    return f"任务 {task.task_id}（{task.task_description[:50]}）状态已更新：{old_status} -> {status}"


@tool(args_schema=UpdateTodolistReadinessInput)
def update_todolist_readiness(session_id: str, ready_to_execute: bool, config: RunnableConfig) -> str:
    """更新任务清单的'可执行'状态。当需求信息已充分时设为 true，当需要进一步澄清时设为 false。"""
    from app.models.agent_model import SupervisorSession

    db = _get_db(config)
    emit = _get_emit(config)

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


# ── 派发工具（异步，统筹 Agent 传递意图给子 Agent） ──


async def _dispatch_outline_coroutine(message: str, work_id: str | None, config: RunnableConfig) -> str:
    """派发大纲任务 — 子 Agent 自行决定创建还是编辑"""
    from app.models.agent_model import SupervisorSession
    from app.services.supervisor.outline_agent import OutlineAgent

    emit = _get_emit(config)
    db = _get_db(config)
    configurable = config.get("configurable", {})
    db_lock = config.get("configurable", {}).get("db_lock")
    session_id = configurable.get("supervisor_session_id")
    session = None
    if session_id:
        session = db.query(SupervisorSession).filter_by(id=session_id).first()

    # 限制：会话一旦绑定作品，禁止在该会话内再创建新作品
    if session and session.work_id and not work_id:
        return (
            "业务规则校验未通过：当前会话已绑定作品，禁止再次创建新作品。"
            f"本会话绑定作品 work_id={session.work_id}，因此本次“创建大纲/作品”请求已拒绝。"
            "请改为编辑该作品大纲（传入该 work_id）。"
        )

    # 保护：若调用方传入 work_id，与会话绑定作品不一致，则拒绝跨作品操作
    if session and session.work_id and work_id and work_id != session.work_id:
        return (
            f"无法执行：当前会话绑定作品为 {session.work_id}，但你传入的是 {work_id}。"
            "请使用当前会话绑定的 work_id，或开启新会话后再操作其他作品。"
        )

    agent = OutlineAgent(emit=emit, user_id=configurable.get("user_id"))

    memories: dict[str, list[str]] = configurable.get("sub_agent_memories", {})

    async def _run_locked(coro):
        """如果有 db_lock（threading.Lock）则直接执行（锁已传给内层 graph）。"""
        return await coro

    if not work_id:
        # 无 work_id → 创建新大纲（直接执行，不需要确认）
        result = await _run_locked(
            agent.create_outline(idea=message, tags=[], db=db, db_lock=db_lock)
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
        _store_memory(memories, "outline", f"创建大纲：{result.get('title', '')}（work_id={result.get('work_id', '')}）")
        return (
            f"大纲创建成功。作品「{result.get('title', '')}」"
            f"（work_id: {result.get('work_id', '')}）"
        )
    else:
        # 有 work_id → 编辑已有大纲
        auto_mode = config.get("configurable", {}).get("auto_mode", False)

        result = await _run_locked(
            agent.edit_outline(
                work_id=work_id, message=message, history=memories.get("outline", []), db=db,
                auto_mode=auto_mode, db_lock=db_lock,
            )
        )
        if result.get("error"):
            return f"编辑大纲失败：{result.get('message', result.get('error', '未知错误'))}"

        _store_memory(memories, "outline", f"编辑大纲 work_id={work_id}：{result.get('message', '')[:300]}")

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
    work_id: str,
    chapter_number: int | None,
    config: RunnableConfig = None,
) -> str:
    """派发章节任务 — 子 Agent 自行决定写新章还是改旧章"""
    from app.models.work_model import Chapter
    from app.services.chapter_outline_sync_service import ChapterOutlineSyncService

    emit = _get_emit(config)
    db = _get_db(config)
    db_lock = config.get("configurable", {}).get("db_lock")
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err

    auto_mode = config.get("configurable", {}).get("auto_mode", False)

    # 如果指定了章节号且该章节已有正文 → 走编辑流程
    if chapter_number is not None:
        existing = db.query(Chapter).filter_by(
            work_id=work_id, chapter_number=chapter_number
        ).first()
        if existing and existing.content:
            return await _edit_chapter_inner(
                work_id=work_id,
                chapter_number=chapter_number,
                user_message=instruction or f"修改第{chapter_number}章",
                auto_mode=auto_mode,
                config=config,
            )

    # 新增章节必须严格顺序：只能新增“当前最大章 + 1”
    max_chapter = db.query(Chapter).filter_by(work_id=work_id).order_by(Chapter.chapter_number.desc()).first()
    expected_next = (max_chapter.chapter_number + 1) if max_chapter else 1

    if chapter_number is None:
        actual_chapter = expected_next
    else:
        actual_chapter = chapter_number

    if actual_chapter != expected_next:
        return (
            "业务规则校验未通过：新增章节必须严格顺序。"
            f"当前已存在至第{expected_next - 1}章，因此只能新增第{expected_next}章，"
            f"不能新增第{actual_chapter}章。本次请求已拒绝。"
            f"请改为“写第{expected_next}章”或“写下一章”。"
        )

    # 否则走写章节流程（由 ChapterAgentGraph 处理）
    # 写作前拼接“全前文梗概 + 事实索引 + 按需原文片段”上下文包，减少跨章冲突。
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

    emit("stage_start", {"stage": "chapter_write", "label": f"写第{actual_chapter}章"})

    from app.services.agent.graph import ChapterAgentGraph

    try:
        graph = ChapterAgentGraph(
            work_id=work_id, chapter_number=actual_chapter,
            db=db, emit=emit, auto_mode=True, db_lock=db_lock,
        )
        agent_record = await graph.start(instruction=enriched_instruction)

        if agent_record.status == "error":
            return f"第{actual_chapter}章写作失败。"

        # 写后：生成并保存章节元数据。
        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=actual_chapter).first()
        if not chapter:
            return f"第{actual_chapter}章写作完成，但未找到章节记录。"

        from app.models.work_model import Work
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            return f"第{actual_chapter}章写作完成，但未找到作品记录。"

        metadata_row = await ChapterOutlineSyncService.generate_and_persist(
            db,
            work=work,
            chapter=chapter,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        return f"第{actual_chapter}章写作失败：{exc!r}"
    emit("chapter_metadata_generated", {
        "chapter_number": actual_chapter,
        "summary": metadata_row.summary,
        "key_plot_points": metadata_row.key_plot_points,
        "outline_links": metadata_row.outline_links,
        "involved_characters": metadata_row.involved_characters,
        "foreshadows": metadata_row.foreshadows,
        "facts": metadata_row.facts,
        "updated_at": metadata_row.updated_at.isoformat() if metadata_row.updated_at else None,
    })

    memories: dict[str, list[str]] = config.get("configurable", {}).get("sub_agent_memories", {})
    _store_memory(memories, "chapter", f"写第{actual_chapter}章完成")

    return (
        f"第{actual_chapter}章写作完成。"
        "已同步章节元数据。"
    )


async def _edit_chapter_inner(
    work_id: str,
    chapter_number: int,
    user_message: str,
    auto_mode: bool,
    config: RunnableConfig,
) -> str:
    """编辑章节的内部实现 — 调用 EditChapterAgent.run() 启动 Tool-Calling 子 Agent"""
    from app.models.agent_model import SupervisorSession
    from app.services.supervisor.edit_chapter_agent import EditChapterAgent

    emit = _get_emit(config)
    db = _get_db(config)
    db_lock = config.get("configurable", {}).get("db_lock")

    agent = EditChapterAgent(emit=emit)

    if auto_mode:
        # 自动模式：直接应用修改
        # 先记录旧内容（apply_edit 已在子 agent 内部写库）
        from app.models.work_model import Chapter

        old_chapter = db.query(Chapter).filter_by(
            work_id=work_id, chapter_number=chapter_number
        ).first()
        old_content = old_chapter.content if old_chapter else ""

        result = await agent.run(
            work_id=work_id,
            chapter_number=chapter_number,
            user_message=user_message,
            db=db,
            emit_diff_event=False,
            db_lock=db_lock,
        )

        if result.get("error"):
            return f"编辑第{chapter_number}章失败：{result['error']}"

        # 从 DB 读新内容，计算 diff
        db.refresh(old_chapter) if old_chapter else None
        new_content = old_chapter.content if old_chapter else ""

        from app.services.supervisor.edit_chapter_agent import _build_diff, _summarize_diff
        diff = _build_diff(old_content, new_content)
        summary = _summarize_diff(diff)

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
        return (
            f"（+{summary.get('lines_added', 0)}行 / -{summary.get('lines_removed', 0)}行）。"
        )

    # 默认模式：设置 waiting 状态，等待用户确认
    result = await agent.run(
        work_id=work_id,
        chapter_number=chapter_number,
        user_message=user_message,
        db=db,
        emit_diff_event=True,
        db_lock=db_lock,
    )

    if result.get("error"):
        return f"编辑第{chapter_number}章失败：{result['error']}"

    summary = result.get("summary", {})

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
        return (
            f"第{chapter_number}章修改已完成"
            f"（+{summary.get('lines_added', 0)}行 / -{summary.get('lines_removed', 0)}行）。"
            f"请等待用户确认是否接受修改。"
        )

    return (
        f"第{chapter_number}章修改已完成。"
        f"{result.get('message', '')}"
    )


async def _dispatch_evaluation_coroutine(
    work_id: str,
    chapter_number: int,
    chapter_content: str = "",
    config: RunnableConfig = None,
) -> str:
    """派发章节评估任务给 EvaluationAgent。"""
    from app.services.evaluation_agent import EvaluationAgent

    emit = _get_emit(config)
    db = _get_db(config)
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err

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
        )
    except Exception as exc:
        logger.exception("dispatch_evaluation failed: %s", exc)
        return f"评估失败：{exc}"

    # 存入子 agent 记忆
    summary = f"第{chapter_number}章「{title}」编辑评估：{editor_text[:500]}；读者评估：{reader_text[:500]}；同步性：{sync_text[:300]}"
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
        f"【编辑视角】{editor_text[:800]}\n"
        f"【读者视角】{reader_text[:800]}\n"
        f"【同步性】{sync_text[:800]}"
    )


async def _dispatch_writing_expert_coroutine(
    work_id: str,
    problem_type: str,
    genre_tags: list[str],
    constraints: list[str] | None = None,
    chapter_goal: str = "",
    chapter_number: int | None = None,
    count: int = 8,
    config: RunnableConfig = None,
) -> str:
    """派发写作专家微咨询任务。"""
    from app.services.supervisor.writing_expert_agent import WritingExpertAgent

    emit = _get_emit(config)
    db = _get_db(config)
    work_id, err = _resolve_bound_work_id(config, db, work_id)
    if err:
        return err

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

    _store_memory(memories, "writing_expert", f"写作建议({problem_type})：{str(result.get('recommended_pick', {}))[:300]}")

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
        "如果没有提供 work_id，子 Agent 将创建全新大纲。"
    ),
    args_schema=DispatchOutlineInput,
)

dispatch_chapter = StructuredTool.from_function(
    func=None,
    coroutine=_dispatch_chapter_coroutine,
    name="dispatch_chapter",
    description=(
        "派发章节撰写或编辑任务给章节子 Agent（执行型工具，不是只读查询）。"
        "适用：撰写新章、修改已有章节正文、根据评估建议优化正文。"
        "不适用：仅查看章节元数据（摘要/伏笔/关键情节）→ 用 query_chapter_meta 或 grep_chapter_meta；"
        "仅查看标题/状态/正文预览 → 用 query_chapters；仅在正文中搜关键词 → 用 grep。"
        "子 Agent 分工：无正文或写下一章时由 ChapterAgent 生成正文并落库；"
        "该章已有正文时由 EditChapterAgent 读取正文与元数据后局部或全量修改。"
        "传入 instruction 描述用户意图；建议带上 chapter_number。"
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
    # 状态机工具
    update_task_status,
    update_todolist_readiness,
    # 派发工具
    dispatch_outline,
    dispatch_chapter,
    dispatch_evaluation,
]
