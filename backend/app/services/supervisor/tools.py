"""SupervisorAgent 工具注册 — 查询工具 + 派发工具

架构:
- 查询工具: 统筹 Agent 直接使用 (query_characters, query_chapters, grep)
- 派发工具: 统筹 Agent 将任务描述传给子 Agent, 子 Agent 自己决定如何执行
  - dispatch_outline: 派发给 OutlineAgent (创建/编辑大纲)
  - dispatch_chapter: 派发给 ChapterAgent / EditChapterAgent (写/改章节)
  - dispatch_evaluation: 派发给 EvaluationAgent (章节质量评估)
"""

from __future__ import annotations

import logging

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


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


class GrepInput(BaseModel):
    work_id: str = Field(description="作品ID")
    keyword: str = Field(description="搜索关键词")
    scope: str = Field(default="all", description="搜索范围: all / characters / chapters")
    context_chars: int = Field(default=200, description="上下文字符数")


class DispatchOutlineInput(BaseModel):
    message: str = Field(description="任务描述：用户想要对大纲做什么，如「丰富大纲，增加女主角戏份」或「从零创建一个末日科幻故事」")
    work_id: str | None = Field(default=None, description="作品ID。已有作品时传入，不传则视为创建新大纲")


class DispatchChapterInput(BaseModel):
    work_id: str = Field(description="作品ID")
    instruction: str = Field(default="", description="任务描述：用户想要对章节做什么，如「写第一章」「修改第三章的结尾」「继续写下一章」")
    chapter_number: int | None = Field(default=None, description="章节号。不传时由子 Agent 根据上下文自行判断")
    auto_apply: bool = Field(
        default=False,
        description="仅用于编辑已有章节时：是否自动应用修改并保存。true 时不会等待用户确认。",
    )


class DispatchEvaluationInput(BaseModel):
    work_id: str = Field(description="作品ID")
    chapter_number: int = Field(description="要评估的章节号")
    chapter_content: str = Field(
        default="",
        description="可选：要评估的正文草稿。不传时 EvaluationAgent 读取数据库中已保存的章节正文",
    )


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


def _format_characters(results: list[dict]) -> str:
    if not results:
        return "没有找到匹配的角色。"
    lines = []
    for c in results:
        parts = [f"【{c['name']}】{c['role_type']}"]
        for key in ("gender", "age", "personality", "background", "current_status", "current_goal"):
            if c.get(key):
                label_map = {
                    "gender": "性别", "age": "年龄", "personality": "性格",
                    "background": "背景", "current_status": "状态", "current_goal": "目的",
                }
                parts.append(f"{label_map[key]}：{c[key]}")
        lines.append("，".join(parts))
    return "\n".join(lines)


def _format_chapters(results: list[dict]) -> str:
    if not results:
        return "没有找到匹配的章节。"
    lines = []
    for ch in results:
        lines.append(f"第{ch['chapter_number']}章 {ch['title']}（{ch['status']}）：{ch['content_preview']}")
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
    results = CharacterService.query_data(work_id=work_id, target="characters", filters=filters, db=db)
    return _format_characters(results)


@tool(args_schema=QueryChaptersInput)
def query_chapters(work_id: str, filters: dict, config: RunnableConfig) -> str:
    """结构化查询章节。支持按章节号范围、标题模糊搜索、状态过滤。"""
    from app.services.character_service import CharacterService

    db = _get_db(config)
    results = CharacterService.query_data(work_id=work_id, target="chapters", filters=filters, db=db)
    return _format_chapters(results)


@tool(args_schema=GrepInput)
def grep(work_id: str, keyword: str, scope: str, context_chars: int, config: RunnableConfig) -> str:
    """关键词全文搜索。在角色设定和/或章节正文中搜索指定关键词，返回上下文片段。"""
    from app.services.character_service import CharacterService

    db = _get_db(config)
    results = CharacterService.grep(
        work_id=work_id, keyword=keyword, scope=scope,
        context_chars=context_chars, db=db,
    )
    return _format_grep(results, keyword)


# ── 派发工具（异步，统筹 Agent 传递意图给子 Agent） ──


async def _dispatch_outline_coroutine(message: str, work_id: str | None, config: RunnableConfig) -> str:
    """派发大纲任务 — 子 Agent 自行决定创建还是编辑"""
    from app.services.supervisor.outline_agent import OutlineAgent

    emit = _get_emit(config)
    db = _get_db(config)

    agent = OutlineAgent(emit=emit)

    if not work_id:
        # 无 work_id → 创建新大纲（直接执行，不需要确认）
        emit("stage_start", {"stage": "outline_create", "label": "创建大纲"})
        result = await agent.create_outline(idea=message, tags=[], db=db)
        if result.get("error"):
            return f"创建大纲失败：{result['error']}"
        created_work_id = result.get("work_id")
        if created_work_id:
            # 关键修复：创建成功后将 work_id 绑定到当前 supervisor session，
            # 否则作品详情页按 work_id 查询时看不到这次对话。
            from app.models.agent_model import SupervisorSession
            from app.models.message_model import Message

            session_id = config.get("configurable", {}).get("supervisor_session_id")
            if session_id:
                sess = db.query(SupervisorSession).filter_by(id=session_id).first()
                if sess:
                    sess.work_id = created_work_id
                db.query(Message).filter(
                    Message.session_id == session_id,
                    Message.work_id.is_(None),
                ).update({"work_id": created_work_id}, synchronize_session=False)
                db.commit()
        return (
            f"大纲创建成功。作品「{result.get('title', '')}」"
            f"（work_id: {result.get('work_id', '')}）"
        )
    else:
        # 有 work_id → 编辑已有大纲（两阶段流程：dry_run → 等待确认）
        result = await agent.edit_outline(work_id=work_id, message=message, history=[], db=db)
        if result.get("error"):
            return f"编辑大纲失败：{result.get('message', result.get('error', '未知错误'))}"

        outline_summary = result.get("outline_summary", {})
        character_summary = result.get("character_summary", {})
        ops = result.get("operations", [])

        # 将 session 设为 waiting 状态，存储 active_child 信息
        from app.models.agent_model import SupervisorSession

        session_id = config.get("configurable", {}).get("supervisor_session_id")
        if session_id:
            sess = db.query(SupervisorSession).filter_by(id=session_id).first()
            if sess:
                sess.active_child = {
                    "type": "edit_outline",
                    "work_id": work_id,
                }
                sess.status = "waiting"
                sess.stage = "executing"
                # 注意：不 commit，因为 dry_run 的数据还在事务中，
                # 等 confirm 时再统一 commit

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
    auto_apply: bool = False,
    config: RunnableConfig = None,
) -> str:
    """派发章节任务 — 子 Agent 自行决定写新章还是改旧章"""
    from app.models.work_model import Chapter

    emit = _get_emit(config)
    db = _get_db(config)

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
                auto_apply=auto_apply,
                config=config,
            )

    # 否则走写章节流程（由 ChapterAgentGraph 处理）
    actual_chapter = chapter_number or 1  # 默认从第 1 章开始
    emit("stage_start", {"stage": "chapter_write", "label": f"写第{actual_chapter}章"})

    from app.services.agent.graph import ChapterAgentGraph

    graph = ChapterAgentGraph(
        work_id=work_id, chapter_number=actual_chapter,
        db=db, emit=emit, auto_mode=True,
    )
    agent_record = await graph.start(instruction=instruction)

    if agent_record.status == "error":
        return f"第{actual_chapter}章写作失败。"
    return f"第{actual_chapter}章写作完成。"


async def _edit_chapter_inner(
    work_id: str,
    chapter_number: int,
    user_message: str,
    auto_apply: bool,
    config: RunnableConfig,
) -> str:
    """编辑章节的内部实现（从旧 edit_chapter 工具迁移而来）"""
    from app.models.agent_model import SupervisorSession
    from app.services.supervisor.edit_chapter_agent import EditChapterAgent

    emit = _get_emit(config)
    db = _get_db(config)

    emit("stage_start", {"stage": "edit_chapter", "label": f"修改第{chapter_number}章"})

    agent = EditChapterAgent(emit=emit)
    result = await agent.edit(
        work_id=work_id, chapter_number=chapter_number,
        user_message=user_message,
        db=db,
        emit_diff_event=not auto_apply,
    )

    if result.get("error"):
        return f"编辑第{chapter_number}章失败：{result['error']}"

    summary = result.get("summary", {})

    if auto_apply:
        # 评估后自动优化：直接保存，不进入 waiting/confirm
        saved = agent.accept_edit(
            work_id=work_id,
            chapter_number=chapter_number,
            new_content=result.get("new_content", ""),
            db=db,
            emit_event=False,
        )
        if saved.get("error"):
            return f"第{chapter_number}章自动优化保存失败：{saved['error']}"
        emit("edit_chapter_auto_applied", {
            "chapter_number": chapter_number,
            "title": saved.get("title", ""),
            "word_count": saved.get("word_count", 0),
            "summary": summary,
            "diff": result.get("diff", []),
        })
        return (
            f"第{chapter_number}章已根据评估建议自动优化并保存"
            f"（+{summary.get('lines_added', 0)}行 / -{summary.get('lines_removed', 0)}行）。"
        )

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
            db.commit()

    return (
        f"第{chapter_number}章修改建议已生成"
        f"（+{summary.get('lines_added', 0)}行 / -{summary.get('lines_removed', 0)}行）。"
        f"请等待用户确认是否接受修改。"
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

    emit("stage_start", {"stage": "evaluation", "label": f"评估第{chapter_number}章"})

    agent = EvaluationAgent()
    try:
        title, editor, reader = await agent.evaluate_chapter(
            db=db,
            work_id=work_id,
            chapter_number=chapter_number,
            chapter_content_override=chapter_content,
        )
    except ValueError as exc:
        return f"评估失败：{exc}"
    except Exception as exc:
        logger.exception("dispatch_evaluation failed: %s", exc)
        return f"评估失败：{exc}"

    emit("evaluation_done", {
        "chapter_number": chapter_number,
        "chapter_title": title,
        "editor": editor.model_dump(),
        "reader": reader.model_dump(),
    })

    def _brief(role: str, result) -> str:
        issues = "；".join(result.issues[:3]) if result.issues else "暂无明显问题"
        suggestions = "；".join(result.suggestions[:3]) if result.suggestions else "暂无建议"
        return f"{role} {result.total_score}/60。问题：{issues}。建议：{suggestions}"

    return (
        f"第{chapter_number}章「{title}」评估完成。\n"
        f"{_brief('编辑视角', editor)}\n"
        f"{_brief('读者视角', reader)}"
    )


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
        "派发章节任务给章节子 Agent。"
        "当用户想要撰写新章节或修改已有章节时使用。"
        "传入任务描述，子 Agent 会自行决定如何执行（撰写新章或编辑已有章节内容）。"
        "当 auto_apply=true 且命中编辑流程时，将直接保存修改，不等待用户确认。"
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


# ── 导出所有工具列表 ──

ALL_TOOLS = [
    query_characters,
    query_chapters,
    grep,
    dispatch_outline,
    dispatch_chapter,
    dispatch_evaluation,
]
