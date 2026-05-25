"""OutlineAgent 工具集

大纲子 Agent 可调用的工具，封装大纲读取、角色查询、大纲生成/编辑和 diff 计算。
"""

from __future__ import annotations

import copy
import json
import logging

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── Tool input schemas ──


class ReadOutlineInput(BaseModel):
    work_id: str = Field(description="作品ID")


class QueryOutlineCharactersInput(BaseModel):
    work_id: str = Field(description="作品ID")


class QueryOutlineRelatedChaptersInput(BaseModel):
    work_id: str = Field(description="作品ID")
    outline_queries: list[str] = Field(default_factory=list, description="大纲片段查询词列表：可传多个节点ID或关键词")
    outline_query: str | None = Field(default=None, description="兼容字段：单个查询词")
    chapter_start: int | None = Field(default=None, description="可选：起始章节号")
    chapter_end: int | None = Field(default=None, description="可选：结束章节号")
    chapter_limit: int = Field(default=10, ge=1, le=100, description="返回章节上限")


class GenerateOutlineInput(BaseModel):
    idea: str = Field(description="故事创意/灵感描述")
    tags: list[str] = Field(default_factory=list, description="题材标签列表")


class EditOutlineInput(BaseModel):
    work_id: str = Field(description="作品ID")
    message: str = Field(description="编辑指令：用户想要对大纲做什么")


class EditOutlineBySuggestionInput(BaseModel):
    work_id: str = Field(description="作品ID")
    suggestion: str = Field(description="修改建议（自然语言）")
    context_note: str = Field(default="", description="可选：补充上下文（自然语言）")


class ReplaceOutlineFieldInput(BaseModel):
    work_id: str = Field(description="作品ID")
    path: str = Field(
        description="字段路径，例如 story.synopsis 或 timeline[id=T1].summary"
    )
    old_value: str = Field(default="", description="期望旧值（乐观锁）")
    new_value: str = Field(default="", description="新值")
    op_id: str = Field(default="", description="可选：操作ID，便于审计")
    reason: str = Field(default="", description="可选：变更原因")


class ReplaceOutlineFieldItem(BaseModel):
    path: str = Field(description="字段路径，例如 story.synopsis 或 timeline[id=T1].summary")
    old_value: str = Field(default="", description="期望旧值（乐观锁）")
    new_value: str = Field(default="", description="新值")
    reason: str = Field(default="", description="可选：变更原因")
    op_id: str = Field(default="", description="可选：操作ID，便于审计")


class ReplaceOutlineFieldsInput(BaseModel):
    work_id: str = Field(description="作品ID")
    updates: list[ReplaceOutlineFieldItem] = Field(default_factory=list, description="批量替换项")


class InsertOutlineItemInput(BaseModel):
    work_id: str = Field(description="作品ID")
    path: str = Field(description="目标列表路径：timeline/branches/foreshadowing")
    mode: str = Field(description="插入模式：append/after_id/before_id/index")
    anchor_id: str = Field(default="", description="锚点ID（after_id/before_id 时使用）")
    index: int = Field(default=-1, description="插入位置（index 模式时使用）")
    item: dict = Field(description="插入对象")
    op_id: str = Field(default="", description="可选：操作ID，便于审计")
    reason: str = Field(default="", description="可选：变更原因")


class DeleteOutlineItemInput(BaseModel):
    work_id: str = Field(description="作品ID")
    path: str = Field(description="目标列表路径：timeline/branches/foreshadowing")
    match_field: str = Field(description="匹配字段，如 id/name")
    match_value: str = Field(description="匹配值")
    op_id: str = Field(default="", description="可选：操作ID，便于审计")
    reason: str = Field(default="", description="可选：变更原因")


class ReplaceCharacterFieldInput(BaseModel):
    work_id: str = Field(description="作品ID")
    character_name: str = Field(description="角色名")
    field: str = Field(description="角色字段名")
    old_value: str = Field(default="", description="期望旧值（乐观锁）")
    new_value: str = Field(default="", description="新值")
    op_id: str = Field(default="", description="可选：操作ID，便于审计")
    reason: str = Field(default="", description="可选：变更原因")


class AddCharacterInput(BaseModel):
    name: str = Field(description="角色名")
    role_type: str = Field(default="配角", description="角色类型")
    gender: str = Field(default="", description="性别")
    age: str = Field(default="", description="年龄")
    appearance: str = Field(default="", description="外貌")
    personality: str = Field(default="", description="性格")
    background: str = Field(default="", description="背景")
    skills: str = Field(default="", description="能力")
    current_status: str = Field(default="存活", description="当前状态")
    current_goal: str = Field(default="", description="当前目标")
    first_chapter: int = Field(default=1, description="首次出场章节")
    notes: str = Field(default="", description="备注")


class DeleteCharacterInput(BaseModel):
    name: str = Field(description="要删除的角色名")


class CommitOrRollbackInput(BaseModel):
    work_id: str = Field(description="作品ID")
    action: str = Field(description="操作：commit 或 rollback")


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


def _get_db_lock(config: RunnableConfig):
    """获取 db_lock（threading.Lock 或 None）。"""
    return config.get("configurable", {}).get("db_lock")


def _with_lock(config: RunnableConfig):
    """返回一个上下文管理器：如果有 db_lock 则加锁，否则无操作。"""
    lock = _get_db_lock(config)
    if lock is not None:
        return lock
    from contextlib import nullcontext
    return nullcontext()


def _atomic_result(
    *,
    status: str,
    tool: str,
    op_id: str,
    message: str,
    diff: dict | None = None,
    conflict_detail: str = "",
) -> str:
    payload = {
        "status": status,
        "tool": tool,
        "op_id": op_id or "",
        "message": message,
        "diff": diff or {},
        "conflict_detail": conflict_detail or "",
    }
    import json

    return json.dumps(payload, ensure_ascii=False)


def _parse_outline_path(path: str) -> tuple[str, str | None, str | None]:
    """Parse path like `story.synopsis` or `timeline[id=T1].summary`."""
    p = (path or "").strip()
    if not p:
        raise ValueError("path 不能为空")

    if "." not in p:
        return p, None, None

    head, field = p.split(".", 1)
    if "[" in head and head.endswith("]"):
        list_name, expr = head.split("[", 1)
        expr = expr[:-1]
        if not expr.startswith("id="):
            raise ValueError("仅支持按 id 选择节点，例如 timeline[id=T1].summary")
        return list_name, expr[3:], field
    return head, None, field


def _apply_single_outline_field_replace(
    *,
    outline: dict,
    path: str,
    old_value: str,
    new_value: str,
    op_id: str = "",
    reason: str = "",
) -> dict:
    """Apply one replace op in-memory and return structured result payload dict."""
    section, node_id, field = _parse_outline_path(path)

    if field is None:
        return {
            "status": "error",
            "tool": "replace_outline_field",
            "op_id": op_id or "",
            "message": f"path 非法：{path}（需要字段路径）",
            "diff": {},
            "conflict_detail": "",
        }

    target = None
    if node_id is None:
        target = outline.get(section, {})
    else:
        arr = outline.get(section, [])
        for item in arr:
            if str(item.get("id", "")) == node_id:
                target = item
                break

    if target is None:
        return {
            "status": "error",
            "tool": "replace_outline_field",
            "op_id": op_id or "",
            "message": f"path 未命中：{path}",
            "diff": {},
            "conflict_detail": "",
        }

    actual_old = str(target.get(field, ""))
    if actual_old != str(old_value):
        return {
            "status": "conflict",
            "tool": "replace_outline_field",
            "op_id": op_id or "",
            "message": f"字段旧值不匹配：{path}",
            "diff": {"path": path, "old": actual_old, "new": str(new_value)},
            "conflict_detail": f"expected={old_value} actual={actual_old}",
        }

    target[field] = new_value
    return {
        "status": "applied",
        "tool": "replace_outline_field",
        "op_id": op_id or "",
        "message": f"已替换字段 {path}",
        "diff": {"path": path, "old": actual_old, "new": new_value, "reason": reason or ""},
        "conflict_detail": "",
    }


# ── 工具实现 ──


@tool(args_schema=ReadOutlineInput)
def read_outline(work_id: str, config: RunnableConfig) -> str:
    """读取作品当前的完整大纲信息。编辑大纲前必须先读取现有数据。"""
    from app.models.work_model import Work

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    outline = work.outline_tree or {}
    story = outline.get("story", {})
    timeline = outline.get("timeline", [])
    foreshadowing = outline.get("foreshadowing", [])

    import json
    parts = [
        f"标题：{work.title}",
        f"类型：{story.get('genre', '未知')}",
        f"卷：{story.get('volume', '未知')}",
        f"时间线节点数：{len(timeline)}",
        f"伏笔数：{len(foreshadowing)}",
    ]
    if story.get("synopsis"):
        parts.append(f"简介：{story['synopsis']}")
    if timeline:
        parts.append(f"\n完整大纲：\n{json.dumps(outline, ensure_ascii=False, indent=2)[:3000]}")

    emit("query_result", {"source": "大纲读取", "summary": f"时间线 {len(timeline)} 节点"})
    return "\n".join(parts)


@tool(args_schema=QueryOutlineCharactersInput)
def query_outline_characters(work_id: str, config: RunnableConfig) -> str:
    """查询作品的所有角色设定。编辑大纲涉及角色变更时应先查询。"""
    from app.models.work_model import Character

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
        characters = db.query(Character).filter_by(work_id=work_id).order_by(
            Character.first_chapter.asc(), Character.created_at.asc()
        ).all()
    if not characters:
        return "该作品暂无角色设定。"

    parts = []
    for c in characters:
        fields = [f"【{c.name}】{c.role_type}"]
        for key, label in [
            ("gender", "性别"), ("age", "年龄"), ("personality", "性格"),
            ("background", "背景"), ("current_status", "状态"),
            ("first_chapter", "首次出场"),
        ]:
            val = getattr(c, key, None)
            if val:
                fields.append(f"{label}：{val}")
        parts.append("，".join(fields))

    emit("query_result", {"source": "角色查询", "summary": f"共 {len(characters)} 个角色"})
    return "\n".join(parts)


@tool(args_schema=QueryOutlineRelatedChaptersInput)
def query_outline_related_chapters(
    work_id: str,
    outline_queries: list[str],
    chapter_limit: int,
    outline_query: str | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    config: RunnableConfig = None,
) -> str:
    """级联查询：先匹配大纲片段，再回查关联章节（基于 chapter_metadata）。"""
    from app.models.work_model import Chapter, ChapterMetadata, Work

    db = _get_db(config)
    emit = _get_emit(config)

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    normalized = [str(x).strip().lower() for x in (outline_queries or []) if str(x).strip()]
    if outline_query and str(outline_query).strip():
        normalized.append(str(outline_query).strip().lower())
    queries = list(dict.fromkeys(normalized))
    if not queries:
        return "查询失败：outline_queries 不能为空。"

    outline = work.outline_tree or {}
    timeline = outline.get("timeline", []) if isinstance(outline, dict) else []
    branches = outline.get("branches", []) if isinstance(outline, dict) else []
    characters = outline.get("characters", []) if isinstance(outline, dict) else []
    foreshadowing = outline.get("foreshadowing", []) if isinstance(outline, dict) else []

    matched_node_ids: set[str] = set()
    outline_hits: list[str] = []

    def _text_hit(parts: list[object], q: str) -> bool:
        merged = " ".join(str(p or "") for p in parts).lower()
        return q in merged

    extra_keywords: set[str] = set()
    for q in queries:
        for node in timeline:
            node_id = str(node.get("id") or "")
            if not node_id:
                continue
            if q == node_id.lower() or _text_hit([
                node.get("id"),
                node.get("development_node"),
                node.get("summary"),
                node.get("time_node"),
            ], q):
                matched_node_ids.add(node_id)
                outline_hits.append(f"[{q}] timeline:{node_id} {node.get('development_node', '')}".strip())

        for item in branches:
            if _text_hit([item.get("id"), item.get("name"), item.get("summary"), item.get("description")], q):
                label = item.get("name") or item.get("id") or "未命名分支"
                outline_hits.append(f"[{q}] branch:{label}")
                extra_keywords.add(str(item.get("name") or "").strip())
        for item in characters:
            if _text_hit([item.get("name"), item.get("role_type"), item.get("background"), item.get("personality")], q):
                name = str(item.get("name") or "").strip()
                if name:
                    outline_hits.append(f"[{q}] character:{name}")
                    extra_keywords.add(name)
        for item in foreshadowing:
            if _text_hit([item.get("id"), item.get("content"), item.get("plant_node"), item.get("payoff_node")], q):
                fid = str(item.get("id") or "unknown")
                outline_hits.append(f"[{q}] foreshadow:{fid}")
                extra_keywords.add(str(item.get("content") or "").strip())

    with _with_lock(config):
        metadata_rows = db.query(ChapterMetadata).filter_by(work_id=work_id).all()
    if not metadata_rows:
        return "暂无章节元数据（chapter_metadata），暂时无法做级联查询。"

    matched: dict[int, dict] = {}
    keywords = queries + [k.lower() for k in extra_keywords if k]
    for b in metadata_rows:
        if chapter_start is not None and b.chapter_number < chapter_start:
            continue
        if chapter_end is not None and b.chapter_number > chapter_end:
            continue
        score = 0
        reasons: list[str] = []

        timeline_ids = [
            str(link.get("id"))
            for link in (b.outline_links or [])
            if isinstance(link, dict) and str(link.get("type", "")).lower() == "timeline"
        ]
        node_hit_ids = [nid for nid in timeline_ids if str(nid) in matched_node_ids]
        if node_hit_ids:
            score += 5
            reasons.append(f"命中节点ID: {', '.join(node_hit_ids)}")

        searchable = " ".join([
            b.summary or "",
            " ".join(str(x) for x in (b.key_plot_points or [])),
            " ".join(str(x) for x in (b.foreshadows or [])),
            " ".join(str(x) for x in (b.facts or [])),
        ]).lower()
        text_hits = [kw for kw in keywords if kw and kw in searchable]
        if text_hits:
            score += min(3, len(text_hits))
            reasons.append(f"命中元数据关键词: {', '.join(text_hits[:3])}")

        if score > 0:
            matched[b.chapter_number] = {"score": score, "reasons": reasons}

    if not matched:
        return (
            f"未找到与「{', '.join(queries)}」相关的章节。"
            "可尝试传入更精确的 timeline 节点ID（如 T1/T2）或更具体的关键词。"
        )

    chapter_numbers = sorted(matched.keys())
    with _with_lock(config):
        chapters = (
            db.query(Chapter)
            .filter(Chapter.work_id == work_id, Chapter.chapter_number.in_(chapter_numbers))
            .all()
        )
    chapter_map = {c.chapter_number: c for c in chapters}

    ranked = sorted(matched.items(), key=lambda x: (-x[1]["score"], x[0]))[:chapter_limit]
    lines = [f"查询词：{', '.join(queries)}", f"命中大纲线索：{'; '.join(outline_hits[:8]) or '无'}", "关联章节："]
    for ch_no, meta in ranked:
        ch = chapter_map.get(ch_no)
        title = ch.title if ch else f"第{ch_no}章"
        status = ch.status if ch else "未知"
        reason = "；".join(meta["reasons"])
        lines.append(f"- 第{ch_no}章 {title}（{status}，score={meta['score']}）：{reason}")

    emit("query_result", {"source": "大纲关联章节", "summary": f"命中 {len(ranked)} 章"})
    return "\n".join(lines)


async def _generate_outline_coroutine(idea: str, tags: list[str], config: RunnableConfig) -> str:
    """从零生成大纲。"""
    from app.schemas.work_schema import OutlineQuickGenerateRequest
    from app.services.work_service import WorkService

    db = _get_db(config)
    emit = _get_emit(config)

    emit("stage_start", {"stage": "outline_create", "label": "创建大纲"})

    payload = OutlineQuickGenerateRequest(idea=idea, tags=tags)
    result = {}

    def capture_emit(event: str, data: dict):
        emit(event, data)
        if event == "outline_done":
            result["work_id"] = data.get("work_id")
            result["title"] = data.get("title")

    user_id = config.get("configurable", {}).get("user_id")
    if not user_id:
        return "大纲生成失败：未认证用户，无法创建作品。"

    svc = WorkService()
    await svc.generate_outline_stream(payload, capture_emit, user_id=user_id)

    if not result.get("work_id"):
        return "大纲生成失败。"

    # 绑定 work_id 到 supervisor session
    session_id = config.get("configurable", {}).get("supervisor_session_id")
    if session_id:
        from app.models.agent_model import SupervisorSession
        from app.models.message_model import Message

        sess = db.query(SupervisorSession).filter_by(id=session_id).first()
        if sess:
            sess.work_id = result["work_id"]
            db.query(Message).filter(
                Message.session_id == session_id,
                Message.work_id.is_(None),
            ).update({"work_id": result["work_id"]}, synchronize_session=False)
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise

    return f"大纲创建成功。作品「{result.get('title', '')}」（work_id: {result.get('work_id', '')}）"


async def _edit_outline_by_suggestion_coroutine(
    work_id: str,
    suggestion: str,
    context_note: str,
    config: RunnableConfig,
) -> str:
    """单入口大纲编辑：外层只传建议，内部独立 LLM 完成具体字段修改。"""
    from app.services.work_service import WorkService

    db = _get_db(config)
    auto_mode = bool(config.get("configurable", {}).get("auto_mode", False))
    dry_run = not auto_mode

    user_message = (suggestion or "").strip()
    note = (context_note or "").strip()
    if note:
        user_message = f"{user_message}\n\n补充上下文：\n{note}"
    if not user_message:
        return _atomic_result(
            status="error",
            tool="edit_outline_by_suggestion",
            op_id="",
            message="suggestion 不能为空。",
        )

    user_id = config.get("configurable", {}).get("user_id")
    if not user_id:
        return _atomic_result(
            status="error",
            tool="edit_outline_by_suggestion",
            op_id="",
            message="未认证用户，无法编辑大纲。",
        )

    svc = WorkService()
    result = await svc.chat_edit_async(
        work_id=work_id,
        user_message=user_message,
        history=[],
        db=db,
        session_id=None,
        dry_run=dry_run,
        max_iterations=1,
        user_id=user_id,
    )

    operations_raw = result.operations or []
    operations: list[dict] = []
    for op in operations_raw:
        if hasattr(op, "model_dump"):
            operations.append(op.model_dump())
        elif isinstance(op, dict):
            operations.append(op)
        else:
            operations.append({"value": str(op)})
    payload = {
        "status": "applied",
        "tool": "edit_outline_by_suggestion",
        "op_id": "",
        "message": "大纲修改已执行。" if not dry_run else "大纲修改已暂存，等待确认。",
        "summary": {
            "dry_run": dry_run,
            "operation_count": len(operations),
        },
        "assistant_message": result.assistant_message or "",
        "operations": operations,
    }
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=ReplaceOutlineFieldInput)
def replace_outline_field(
    work_id: str,
    path: str,
    old_value: str,
    new_value: str,
    op_id: str,
    reason: str,
    config: RunnableConfig,
) -> str:
    """原子替换大纲字段。仅修改一个字段，必须提供 path 与旧值校验。"""
    from app.models.work_model import Work

    db = _get_db(config)
    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(
            status="error",
            tool="replace_outline_field",
            op_id=op_id,
            message=f"作品 {work_id} 不存在。",
        )

    outline = copy.deepcopy(work.outline_tree) if work.outline_tree else {}
    result = _apply_single_outline_field_replace(
        outline=outline,
        path=path,
        old_value=old_value,
        new_value=new_value,
        op_id=op_id,
        reason=reason,
    )
    if result.get("status") == "applied":
        work.outline_tree = outline
    return _atomic_result(
        status=result.get("status", "error"),
        tool="replace_outline_field",
        op_id=result.get("op_id", op_id),
        message=result.get("message", "替换失败"),
        diff=result.get("diff", {}),
        conflict_detail=result.get("conflict_detail", ""),
    )


@tool(args_schema=ReplaceOutlineFieldsInput)
def replace_outline_fields(
    work_id: str,
    updates: list[ReplaceOutlineFieldItem],
    config: RunnableConfig,
) -> str:
    """批量替换多个大纲字段。单次调用可提交多条 path/old/new。"""
    from app.models.work_model import Work
    import json

    db = _get_db(config)
    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(
            status="error",
            tool="replace_outline_fields",
            op_id="",
            message=f"作品 {work_id} 不存在。",
        )

    if not updates:
        return _atomic_result(
            status="error",
            tool="replace_outline_fields",
            op_id="",
            message="updates 不能为空。",
        )

    outline = copy.deepcopy(work.outline_tree) if work.outline_tree else {}
    item_results: list[dict] = []
    applied = 0
    conflict = 0
    error = 0
    for item in updates:
        item_result = _apply_single_outline_field_replace(
            outline=outline,
            path=item.path,
            old_value=item.old_value,
            new_value=item.new_value,
            op_id=item.op_id,
            reason=item.reason,
        )
        st = item_result.get("status")
        if st == "applied":
            applied += 1
        elif st == "conflict":
            conflict += 1
        else:
            error += 1
        item_results.append(item_result)

    if applied > 0:
        work.outline_tree = outline

    overall_status = "applied" if (applied > 0 and conflict == 0 and error == 0) else "partial"
    if applied == 0 and (conflict > 0 or error > 0):
        overall_status = "conflict" if conflict > 0 and error == 0 else "error"

    payload = {
        "status": overall_status,
        "tool": "replace_outline_fields",
        "op_id": "",
        "message": f"批量替换完成：applied={applied}, conflict={conflict}, error={error}",
        "summary": {"applied": applied, "conflict": conflict, "error": error, "total": len(updates)},
        "results": item_results,
    }
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=InsertOutlineItemInput)
def insert_outline_item(
    work_id: str,
    path: str,
    mode: str,
    anchor_id: str,
    index: int,
    item: dict,
    op_id: str,
    reason: str,
    config: RunnableConfig,
) -> str:
    """原子插入大纲节点。支持 append / after_id / before_id / index。"""
    from app.models.work_model import Work

    db = _get_db(config)
    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(status="error", tool="insert_outline_item", op_id=op_id, message=f"作品 {work_id} 不存在。")

    outline = copy.deepcopy(work.outline_tree) if work.outline_tree else {}
    arr = outline.get(path)
    if not isinstance(arr, list):
        return _atomic_result(status="error", tool="insert_outline_item", op_id=op_id, message=f"path 不是列表：{path}")

    insert_at = len(arr)
    if mode == "append":
        insert_at = len(arr)
    elif mode == "index":
        insert_at = max(0, min(index, len(arr)))
    elif mode in ("after_id", "before_id"):
        anchor_idx = -1
        for i, obj in enumerate(arr):
            if str(obj.get("id", "")) == str(anchor_id):
                anchor_idx = i
                break
        if anchor_idx < 0:
            return _atomic_result(
                status="conflict",
                tool="insert_outline_item",
                op_id=op_id,
                message=f"锚点不存在：{anchor_id}",
                conflict_detail=f"path={path}",
            )
        insert_at = anchor_idx + 1 if mode == "after_id" else anchor_idx
    else:
        return _atomic_result(status="error", tool="insert_outline_item", op_id=op_id, message=f"不支持的 mode：{mode}")

    arr.insert(insert_at, item)
    outline[path] = arr
    work.outline_tree = outline
    return _atomic_result(
        status="applied",
        tool="insert_outline_item",
        op_id=op_id,
        message=f"已插入到 {path}[{insert_at}]",
        diff={"path": path, "index": insert_at, "new": item, "reason": reason or ""},
    )


@tool(args_schema=DeleteOutlineItemInput)
def delete_outline_item(
    work_id: str,
    path: str,
    match_field: str,
    match_value: str,
    op_id: str,
    reason: str,
    config: RunnableConfig,
) -> str:
    """原子删除大纲节点。按 match_field + match_value 匹配单条记录。"""
    from app.models.work_model import Work

    db = _get_db(config)
    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(status="error", tool="delete_outline_item", op_id=op_id, message=f"作品 {work_id} 不存在。")

    outline = copy.deepcopy(work.outline_tree) if work.outline_tree else {}
    arr = outline.get(path)
    if not isinstance(arr, list):
        return _atomic_result(status="error", tool="delete_outline_item", op_id=op_id, message=f"path 不是列表：{path}")

    idx = -1
    old_item = None
    for i, obj in enumerate(arr):
        if str(obj.get(match_field, "")) == str(match_value):
            idx = i
            old_item = obj
            break
    if idx < 0:
        return _atomic_result(
            status="conflict",
            tool="delete_outline_item",
            op_id=op_id,
            message=f"未命中待删除项：{match_field}={match_value}",
            conflict_detail=f"path={path}",
        )

    arr.pop(idx)
    outline[path] = arr
    work.outline_tree = outline
    return _atomic_result(
        status="applied",
        tool="delete_outline_item",
        op_id=op_id,
        message=f"已删除 {path} 中 {match_field}={match_value}",
        diff={"path": path, "old": old_item, "reason": reason or ""},
    )


@tool(args_schema=ReplaceCharacterFieldInput)
def replace_character_field(
    work_id: str,
    character_name: str,
    field: str,
    old_value: str,
    new_value: str,
    op_id: str,
    reason: str,
    config: RunnableConfig,
) -> str:
    """原子替换角色字段。只修改一个角色的一个字段。"""
    from app.models.work_model import Character

    db = _get_db(config)
    char = db.query(Character).filter_by(work_id=work_id, name=character_name).first()
    if not char:
        return _atomic_result(
            status="error",
            tool="replace_character_field",
            op_id=op_id,
            message=f"未找到角色：{character_name}",
        )

    if not hasattr(char, field):
        return _atomic_result(
            status="error",
            tool="replace_character_field",
            op_id=op_id,
            message=f"角色字段不存在：{field}",
        )

    actual_old = str(getattr(char, field) or "")
    if actual_old != str(old_value):
        return _atomic_result(
            status="conflict",
            tool="replace_character_field",
            op_id=op_id,
            message=f"角色字段旧值不匹配：{character_name}.{field}",
            diff={"path": f"character:{character_name}.{field}", "old": actual_old, "new": str(new_value)},
            conflict_detail=f"expected={old_value} actual={actual_old}",
        )

    setattr(char, field, new_value)
    return _atomic_result(
        status="applied",
        tool="replace_character_field",
        op_id=op_id,
        message=f"已替换角色字段：{character_name}.{field}",
        diff={"path": f"character:{character_name}.{field}", "old": actual_old, "new": new_value, "reason": reason or ""},
    )


@tool(args_schema=AddCharacterInput)
def add_character(
    name: str,
    role_type: str,
    gender: str,
    age: str,
    appearance: str,
    personality: str,
    background: str,
    skills: str,
    current_status: str,
    current_goal: str,
    first_chapter: int,
    notes: str,
    config: RunnableConfig,
) -> str:
    """新增角色（原子操作）。"""
    from app.models.work_model import Character

    db = _get_db(config)
    work_id = _get_work_id(config)
    existing = db.query(Character).filter_by(work_id=work_id, name=name).first()
    if existing:
        return _atomic_result(
            status="conflict",
            tool="add_character",
            op_id="",
            message=f"角色已存在：{name}",
        )

    char = Character(
        work_id=work_id,
        name=name,
        role_type=role_type,
        gender=gender,
        age=age,
        appearance=appearance,
        personality=personality,
        background=background,
        skills=skills,
        current_status=current_status,
        current_goal=current_goal,
        first_chapter=first_chapter,
        notes=notes,
    )
    db.add(char)
    return _atomic_result(
        status="applied",
        tool="add_character",
        op_id="",
        message=f"已新增角色：{name}",
        diff={"path": f"character:{name}", "new": {"name": name, "role_type": role_type}},
    )


@tool(args_schema=DeleteCharacterInput)
def delete_character(name: str, config: RunnableConfig) -> str:
    """删除角色（原子操作）。"""
    from app.models.work_model import Character

    db = _get_db(config)
    work_id = _get_work_id(config)
    char = db.query(Character).filter_by(work_id=work_id, name=name).first()
    if not char:
        return _atomic_result(
            status="conflict",
            tool="delete_character",
            op_id="",
            message=f"未找到角色：{name}",
        )

    old = {"name": char.name, "role_type": char.role_type}
    db.delete(char)
    return _atomic_result(
        status="applied",
        tool="delete_character",
        op_id="",
        message=f"已删除角色：{name}",
        diff={"path": f"character:{name}", "old": old},
    )


@tool(args_schema=CommitOrRollbackInput)
def commit_or_rollback(work_id: str, action: str, config: RunnableConfig) -> str:
    """确认提交或回滚大纲变更。action 只能是 commit 或 rollback。"""
    db = _get_db(config)
    emit = _get_emit(config)

    if action == "commit":
        try:
            with _with_lock(config):
                db.commit()
        except Exception as exc:
            with _with_lock(config):
                db.rollback()
            return f"大纲变更提交失败：{exc!r}"
        emit("outline_edit_committed", {"work_id": work_id})
        return "大纲变更已提交。"
    elif action == "rollback":
        with _with_lock(config):
            db.rollback()
        emit("outline_edit_rolled_back", {"work_id": work_id})
        return "大纲变更已回滚。"
    else:
        return f"无效操作：{action}。请使用 commit 或 rollback。"


def _character_to_dict(c) -> dict:
    return {
        "name": c.name or "",
        "role_type": c.role_type or "",
        "gender": c.gender or "",
        "age": c.age or "",
        "appearance": c.appearance or "",
        "personality": c.personality or "",
        "background": c.background or "",
        "skills": c.skills or "",
        "current_status": c.current_status or "",
        "current_goal": c.current_goal or "",
        "first_chapter": c.first_chapter or 1,
    }


generate_outline = StructuredTool.from_function(
    func=None,
    coroutine=_generate_outline_coroutine,
    name="generate_outline",
    description="从零创建大纲。传入故事创意和题材标签，生成完整大纲并保存到数据库。",
    args_schema=GenerateOutlineInput,
)

edit_outline_by_suggestion = StructuredTool.from_function(
    func=None,
    coroutine=_edit_outline_by_suggestion_coroutine,
    name="edit_outline_by_suggestion",
    description="单次调用完成大纲编辑。只需传入修改建议和必要上下文，工具内部会读取并修改大纲。",
    args_schema=EditOutlineBySuggestionInput,
)

# ── 导出工具列表 ──

# 基础工具（两种模式共用）
_OUTLINE_BASE_TOOLS = [
    read_outline,
    query_outline_characters,
    query_outline_related_chapters,
    generate_outline,
    edit_outline_by_suggestion,
]


def build_outline_tools(*, auto_mode: bool = True) -> list:
    """根据 auto_mode 构建大纲工具集。

    自动模式（auto_mode=True，默认）：包含 commit_or_rollback，LLM 自行决定提交或回滚。
    手动模式（auto_mode=False）：不含 commit_or_rollback，LLM 只做 dry_run，
    变更暂存在数据库事务中，由用户在 UI 确认后 commit/rollback。
    """
    tools = list(_OUTLINE_BASE_TOOLS)
    if auto_mode:
        tools.append(commit_or_rollback)
    return tools


# 向后兼容：默认包含 commit_or_rollback（自动模式）
OUTLINE_TOOLS = build_outline_tools(auto_mode=True)
