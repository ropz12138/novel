"""Todo Execution Harness — 确定性代码维护任务状态机

职责：
- 查询任务
- 校验任务依赖
- 原子更新任务状态
- 根据任务路由派发子 Agent
- 捕获异常并标记失败
- emit 状态事件
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from langchain_core.runnables import RunnableConfig
from sqlalchemy.orm import Session

from app.models.task_item_model import TaskItem

logger = logging.getLogger(__name__)


# ── owner -> dispatch_tool 推断映射 ──

OWNER_DISPATCH_MAP: dict[str, str] = {
    "outline_agent": "dispatch_outline",
    "chapter_agent": "dispatch_chapter",
    "evaluation_agent": "dispatch_evaluation",
}

TASK_TYPE_DISPATCH_MAP: dict[str, str] = {
    "outline": "dispatch_outline",
    "chapter_write": "dispatch_chapter",
    "chapter_edit": "dispatch_chapter",
    "metadata": "dispatch_chapter",
    "evaluation": "dispatch_evaluation",
}

DISPATCH_OWNER_MAP: dict[str, str] = {
    "dispatch_outline": "outline_agent",
    "dispatch_chapter": "chapter_agent",
    "dispatch_evaluation": "evaluation_agent",
}

AGENT_DISPATCH_MAP: dict[str, str] = {
    "outline": "dispatch_outline",
    "chapter": "dispatch_chapter",
    "evaluation": "dispatch_evaluation",
}

MAX_TASK_RETRIES = 2


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── 序列化 ──


def serialize_task_item(task: TaskItem) -> dict:
    """将 TaskItem 序列化为前端和 emit 需要的 dict"""
    depends_on_raw = task.depends_on or ""
    depends_on_list = [d.strip() for d in depends_on_raw.split(",") if d.strip()] if depends_on_raw else []

    return {
        "db_id": task.id,
        "task_id": task.task_id,
        "task": task.task_description,
        "owner": task.owner,
        "status": task.status,
        "parent_id": getattr(task, "parent_id", None) or "",
        "depth": getattr(task, "depth", 0) or 0,
        "agent_scope": getattr(task, "agent_scope", "") or "",
        "depends_on": depends_on_list,
        "done_criteria": task.done_criteria,
        "task_type": getattr(task, "task_type", "") or "",
        "dispatch_tool": getattr(task, "dispatch_tool", "") or "",
        "instruction": getattr(task, "instruction", "") or "",
        "result_summary": task.result_summary or "",
        "error_message": getattr(task, "error_message", "") or "",
        "retry_count": getattr(task, "retry_count", 0) or 0,
    }


# ── 状态更新 ──


def set_task_status(
    *,
    task: TaskItem,
    status: str,
    db: Session,
    emit: Callable[[str, dict], None],
    result_summary: str = "",
    error_message: str = "",
) -> None:
    """原子更新任务状态、写入时间戳、emit 事件"""
    old_status = task.status
    task.status = status

    now = _utcnow()
    if status == "in_progress" and task.started_at is None:
        task.started_at = now
    if status in ("completed", "failed", "skipped") and task.completed_at is None:
        task.completed_at = now

    if result_summary:
        task.result_summary = result_summary
    if error_message:
        task.error_message = error_message

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    emit("task_status_updated", {
        "task_item_id": task.id,
        "task_id": task.task_id,
        "parent_id": getattr(task, "parent_id", None) or "",
        "depth": getattr(task, "depth", 0) or 0,
        "agent_scope": getattr(task, "agent_scope", "") or "",
        "old_status": old_status,
        "new_status": status,
        "result_summary": result_summary or task.result_summary,
        "error_message": error_message or getattr(task, "error_message", ""),
    })


# ── 清理 ──


def cleanup_session_todolist(
    *,
    session_id: str,
    db: Session,
) -> int:
    """清理指定 session 中所有已有的 todolist 任务（父任务 + 子任务）。

    在 analyze_requirements 创建新 todolist 前调用，防止同一 session 中
    出现多组同名 task_id 的记录，导致依赖检查混乱。

    返回删除的任务数量。
    """
    if not session_id:
        return 0

    # 查询所有父任务（depth=0, parent_id=None）
    parent_tasks = (
        db.query(TaskItem)
        .filter_by(session_id=session_id)
        .filter(
            (TaskItem.depth == 0) | (TaskItem.depth.is_(None)),
            (TaskItem.parent_id.is_(None)) | (TaskItem.parent_id == ""),
        )
        .all()
    )

    if not parent_tasks:
        return 0

    deleted = 0

    # 先删除子任务
    for parent in parent_tasks:
        children = (
            db.query(TaskItem)
            .filter_by(session_id=session_id, parent_id=parent.id)
            .all()
        )
        for child in children:
            db.delete(child)
            deleted += 1

    # 再删除父任务
    for parent in parent_tasks:
        db.delete(parent)
        deleted += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return deleted


# ── 查询 ──


def get_next_executable_task(
    *,
    session_id: str,
    db: Session,
) -> TaskItem | None:
    """返回当前 session 中第一条 pending 且依赖已满足的任务"""
    tasks = (
        db.query(TaskItem)
        .filter_by(session_id=session_id)
        .order_by(TaskItem.sort_order)
        .all()
    )
    tasks = [t for t in tasks if getattr(t, "parent_id", None) in (None, "")]

    # 构建已完成任务 ID 集合
    completed_task_ids: set[str] = set()
    for t in tasks:
        if t.status == "completed":
            completed_task_ids.add(t.task_id)

    for t in tasks:
        if t.status != "pending":
            continue
        # 检查依赖
        depends_on_raw = t.depends_on or ""
        deps = [d.strip() for d in depends_on_raw.split(",") if d.strip()]
        if all(d in completed_task_ids for d in deps):
            return t

    return None


def resolve_task_identifier(
    *,
    task_item_id: str,
    db: Session,
    config: RunnableConfig,
) -> TaskItem | None:
    """解析 LLM 传入的 task id。

    支持 db_id 和 T1/T2 形式。若 task_id 重复，优先选择 pending、可自动执行、
    非澄清类任务，避免误执行旧的 clarify/user_confirmation 任务。
    """
    task = db.query(TaskItem).filter_by(id=task_item_id).first()
    if task:
        return task

    session_id = (config or {}).get("configurable", {}).get("supervisor_session_id")
    query = db.query(TaskItem).filter_by(task_id=task_item_id)
    if session_id:
        query = query.filter_by(session_id=session_id)
    candidates = query.all()
    if not isinstance(candidates, list):
        candidates = []
    if not candidates:
        return None

    def score(candidate: TaskItem) -> tuple:
        task_type = getattr(candidate, "task_type", "") or ""
        dispatch_tool = infer_dispatch_tool(candidate)
        return (
            1 if candidate.status == "pending" else 0,
            1 if getattr(candidate, "parent_id", None) is None else 0,
            1 if dispatch_tool and dispatch_tool != "none" else 0,
            0 if task_type in ("clarify", "user_confirmation") else 1,
            getattr(candidate, "sort_order", 0) or 0,
            getattr(candidate, "created_at", None) or datetime.min.replace(tzinfo=timezone.utc),
        )

    return sorted(candidates, key=score, reverse=True)[0]


def infer_dispatch_tool(task: TaskItem) -> str:
    """从显式字段、owner、task_type 和任务文本推断执行工具。"""
    dispatch_tool = getattr(task, "dispatch_tool", "") or ""
    if dispatch_tool and dispatch_tool != "none":
        return dispatch_tool

    dispatch_tool = OWNER_DISPATCH_MAP.get(task.owner, "")
    if dispatch_tool:
        return dispatch_tool

    task_type = getattr(task, "task_type", "") or ""
    dispatch_tool = TASK_TYPE_DISPATCH_MAP.get(task_type, "")
    if dispatch_tool:
        return dispatch_tool

    text = f"{task.task_description or ''} {getattr(task, 'instruction', '') or ''}"
    if any(keyword in text for keyword in ("评估", "评价", "审稿", "打分")):
        return "dispatch_evaluation"
    if any(keyword in text for keyword in ("章节", "正文", "写第", "撰写", "续写", "改写", "编辑")):
        return "dispatch_chapter"
    if any(keyword in text for keyword in ("大纲", "角色", "主线", "支线", "伏笔", "设定")):
        return "dispatch_outline"

    return ""


# ── 子任务维护 ──


def _get_current_parent_task(
    *,
    db: Session,
    config: RunnableConfig,
) -> TaskItem | None:
    configurable = (config or {}).get("configurable", {})
    current_task_item_id = configurable.get("current_task_item_id")
    if not current_task_item_id:
        return None
    session_id = configurable.get("supervisor_session_id")
    query = db.query(TaskItem).filter_by(id=current_task_item_id)
    if session_id:
        query = query.filter_by(session_id=session_id)
    return query.first()


def _all_session_tasks(*, db: Session, session_id: str) -> list[dict]:
    tasks = (
        db.query(TaskItem)
        .filter_by(session_id=session_id)
        .order_by(TaskItem.depth.asc(), TaskItem.sort_order.asc(), TaskItem.created_at.asc())
        .all()
    )
    return [serialize_task_item(t) for t in tasks]


def _allocate_child_task_id(
    *,
    raw_task_id: str,
    parent_task_id: str,
    index: int,
    used_ids: set[str],
) -> str:
    """Allocate a deterministic parent-scoped child task id."""
    base = f"{parent_task_id}.{index}"
    if base not in used_ids:
        used_ids.add(base)
        return base

    suffix = 2
    while f"{base}_{suffix}" in used_ids:
        suffix += 1
    final_id = f"{base}_{suffix}"
    used_ids.add(final_id)
    return final_id


def create_child_todolist(
    *,
    items: list[dict],
    db: Session,
    emit: Callable[[str, dict], None],
    config: RunnableConfig,
) -> str:
    """为当前执行中的父任务创建子 Agent 内部子任务清单。"""
    parent = _get_current_parent_task(db=db, config=config)
    if not parent:
        return "创建子任务失败：当前没有可绑定的父任务。"
    if not items:
        return "创建子任务失败：items 不能为空。"

    existing = (
        db.query(TaskItem)
        .filter_by(session_id=parent.session_id, parent_id=parent.id)
        .order_by(TaskItem.sort_order.asc(), TaskItem.created_at.asc())
        .all()
    )
    if existing:
        return f"父任务 {parent.task_id} 已存在 {len(existing)} 个子任务，请使用 read_child_todolist 查看或 update_child_task_status 更新。"

    normalized_items: list[tuple[int, dict, str]] = []
    raw_id_to_new: dict[str, str] = {}
    used_ids = {str(t.task_id or "").strip() for t in existing}
    for idx, raw in enumerate(items, start=1):
        desc = str(raw.get("task") or raw.get("task_description") or "").strip()
        if not desc:
            continue
        child_task_id = _allocate_child_task_id(
            raw_task_id=str(raw.get("id") or ""),
            parent_task_id=parent.task_id,
            index=idx,
            used_ids=used_ids,
        )
        raw_id = str(raw.get("id") or "").strip()
        if raw_id:
            raw_id_to_new[raw_id] = child_task_id
        raw_id_to_new.setdefault(f"T{idx}", child_task_id)
        normalized_items.append((idx, raw, child_task_id))

    created: list[TaskItem] = []
    agent_scope = parent.owner or "sub_agent"
    for idx, raw, child_task_id in normalized_items:
        desc = str(raw.get("task") or raw.get("task_description") or "").strip()
        raw_depends_on = raw.get("depends_on") or []
        if isinstance(raw_depends_on, list):
            depends_on = ",".join(raw_id_to_new.get(str(dep).strip(), str(dep).strip()) for dep in raw_depends_on if str(dep).strip())
        else:
            depends_on = ",".join(
                raw_id_to_new.get(dep.strip(), dep.strip())
                for dep in str(raw_depends_on or "").split(",")
                if dep.strip()
            )
        child = TaskItem(
            id=str(uuid.uuid4()),
            session_id=parent.session_id,
            parent_id=parent.id,
            depth=(getattr(parent, "depth", 0) or 0) + 1,
            agent_scope=agent_scope,
            task_id=child_task_id,
            task_description=desc,
            owner=agent_scope,
            status=str(raw.get("status") or "pending"),
            depends_on=depends_on,
            done_criteria=str(raw.get("done_criteria") or ""),
            task_type=str(raw.get("task_type") or "subtask"),
            dispatch_tool="none",
            instruction=str(raw.get("instruction") or desc),
            sort_order=idx,
        )
        db.add(child)
        created.append(child)

    if not created:
        return "创建子任务失败：没有有效的任务描述。"

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    subtasks = [serialize_task_item(t) for t in created]
    emit("subtasks_created", {
        "parent_task_item_id": parent.id,
        "parent_task_id": parent.task_id,
        "subtasks": subtasks,
        "todolist": _all_session_tasks(db=db, session_id=parent.session_id),
    })
    mapping_lines = [
        f"{str(raw.get('id') or f'T{idx}').strip()} -> {child_id}"
        for idx, raw, child_id in normalized_items
        if str(raw.get("id") or f"T{idx}").strip() != child_id
    ]
    mapping_text = "\n编号映射：\n" + "\n".join(f"- {line}" for line in mapping_lines) if mapping_lines else ""
    return f"已为父任务 {parent.task_id} 创建 {len(created)} 个子任务。{mapping_text}"


def read_child_todolist(
    *,
    db: Session,
    config: RunnableConfig,
) -> str:
    """读取当前父任务下的子任务清单。"""
    parent = _get_current_parent_task(db=db, config=config)
    if not parent:
        return "读取子任务失败：当前没有可绑定的父任务。"
    children = (
        db.query(TaskItem)
        .filter_by(session_id=parent.session_id, parent_id=parent.id)
        .order_by(TaskItem.sort_order.asc(), TaskItem.created_at.asc())
        .all()
    )
    if not children:
        return f"父任务 {parent.task_id} 暂无子任务。"
    lines = [f"父任务 {parent.task_id}：{parent.task_description}"]
    for child in children:
        lines.append(f"- {child.task_id} [{child.status}] {child.task_description}")
    return "\n".join(lines)


def update_child_task_status(
    *,
    task_identifier: str,
    status: str,
    db: Session,
    emit: Callable[[str, dict], None],
    config: RunnableConfig,
    result_summary: str = "",
    error_message: str = "",
) -> str:
    """更新当前父任务范围内的子任务状态。"""
    parent = _get_current_parent_task(db=db, config=config)
    if not parent:
        return "更新子任务失败：当前没有可绑定的父任务。"

    task = (
        db.query(TaskItem)
        .filter_by(session_id=parent.session_id, parent_id=parent.id, id=task_identifier)
        .first()
    )
    if not task:
        task = (
            db.query(TaskItem)
            .filter_by(session_id=parent.session_id, parent_id=parent.id, task_id=task_identifier)
            .first()
        )
    if not task:
        legacy_match = re.fullmatch(r"T(\d+)", str(task_identifier or "").strip())
        if legacy_match:
            mapped_identifier = f"{parent.task_id}.{int(legacy_match.group(1))}"
            task = (
                db.query(TaskItem)
                .filter_by(session_id=parent.session_id, parent_id=parent.id, task_id=mapped_identifier)
                .first()
            )
    if not task:
        return f"更新子任务失败：父任务 {parent.task_id} 下不存在 {task_identifier}。"

    if status not in {"pending", "in_progress", "completed", "failed", "skipped"}:
        return f"更新子任务失败：不支持的状态 {status}。"

    set_task_status(
        task=task,
        status=status,
        db=db,
        emit=emit,
        result_summary=result_summary,
        error_message=error_message,
    )
    return f"子任务 {task.task_id} 已更新为 {status}。"


def finalize_open_child_tasks(
    *,
    parent: TaskItem,
    final_status: str,
    db: Session,
    emit: Callable[[str, dict], None],
    result_summary: str = "",
    error_message: str = "",
) -> None:
    """父任务结束时兜底收敛仍未进入终态的子任务状态。"""
    children = (
        db.query(TaskItem)
        .filter_by(session_id=parent.session_id, parent_id=parent.id)
        .filter(TaskItem.status.in_(["pending", "in_progress"]))
        .order_by(TaskItem.sort_order.asc(), TaskItem.created_at.asc())
        .all()
    )
    for child in children:
        set_task_status(
            task=child,
            status=final_status,
            db=db,
            emit=emit,
            result_summary=result_summary,
            error_message=error_message,
        )


def build_subtask_digest(*, parent: TaskItem, db: Session) -> str:
    """把父任务下的子任务汇总成可读明细（做了什么 / 哪步失败）。"""
    children = (
        db.query(TaskItem)
        .filter_by(session_id=parent.session_id, parent_id=parent.id)
        .order_by(TaskItem.sort_order.asc(), TaskItem.created_at.asc())
        .all()
    )
    if not isinstance(children, list) or not children:
        return ""

    marks = {
        "completed": "✓",
        "failed": "✗",
        "skipped": "-",
        "in_progress": "…",
        "pending": "·",
    }
    lines = ["执行明细："]
    for child in children:
        detail = child.result_summary or child.error_message or child.task_description
        lines.append(f"  {marks.get(child.status, '?')} [{child.task_id}] {detail}")
    return "\n".join(lines)


def _report_digest(dispatch_result: dict | None) -> str:
    if not dispatch_result:
        return ""
    report = dispatch_result.get("report")
    if isinstance(report, dict):
        lines = ["子 Agent 汇报："]
        summary = str(report.get("summary") or "").strip()
        if summary:
            lines.append(f"- 总结：{summary}")
        for label, key in [
            ("关键动作", "actions"),
            ("产出物", "artifacts"),
            ("遗留问题", "issues"),
            ("后续建议", "next_suggestions"),
        ]:
            values = report.get(key)
            if isinstance(values, list) and values:
                lines.append(f"- {label}：" + "；".join(str(v) for v in values if str(v).strip()))
        return "\n".join(lines)

    payload = dispatch_result.get("payload")
    if isinstance(payload, dict):
        parts = []
        for key in ("title", "work_id", "chapter_number", "editor", "reader", "sync"):
            value = payload.get(key)
            if value not in (None, "", [], {}):
                parts.append(f"{key}={value}")
        if parts:
            return "结构化结果：" + "；".join(parts)
    return ""


def _compose_task_summary(
    *,
    result_message: str,
    dispatch_result: dict | None,
    subtask_digest: str,
) -> str:
    parts = [part for part in [result_message, _report_digest(dispatch_result), subtask_digest] if part]
    return "\n".join(parts)


def _clear_child_tasks_for_retry(*, parent: TaskItem, db: Session, emit: Callable[[str, dict], None]) -> int:
    children = (
        db.query(TaskItem)
        .filter_by(session_id=parent.session_id, parent_id=parent.id)
        .all()
    )
    if not isinstance(children, list) or not children:
        return 0
    deleted = 0
    for child in children:
        db.delete(child)
        deleted += 1
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    emit("subtasks_cleared_for_retry", {
        "parent_task_item_id": parent.id,
        "parent_task_id": parent.task_id,
        "deleted": deleted,
    })
    return deleted


# ── 执行 ──


async def execute_todo_task(
    *,
    task_item_id: str,
    db: Session,
    emit: Callable[[str, dict], None],
    config: RunnableConfig,
    agent: str | None = None,
) -> str:
    """执行 todolist 中的一条任务

    流程：查询 -> 校验依赖 -> 设 in_progress -> 派发 -> 设 completed/failed
    """
    # 1. 查询任务（支持 db_id 与 T1/T2；重复 task_id 时做确定性选择）
    task = resolve_task_identifier(task_item_id=task_item_id, db=db, config=config)
    if not task:
        return f"任务记录 {task_item_id} 不存在。请使用 read_todolist 查看可用任务。"

    task_type = getattr(task, "task_type", "") or ""
    if task_type in ("clarify", "user_confirmation"):
        return (
            f"任务 {task.task_id}（{task.task_description}）是用户澄清/确认任务，"
            "不可自动执行。请等待用户补充信息，或重新生成可执行 todolist。"
        )

    # 2. 检查是否已在执行
    if task.status == "in_progress":
        return f"任务 {task.task_id}（{task.task_description}）已在执行中，请勿重复执行。"

    # 3. 检查是否已是终态
    if task.status in ("completed", "skipped"):
        return f"任务 {task.task_id} 当前状态为 {task.status}，不可执行。"
    if task.status == "failed":
        retry_count = getattr(task, "retry_count", 0) or 0
        if retry_count >= MAX_TASK_RETRIES:
            return f"任务 {task.task_id} 已达重试上限（{MAX_TASK_RETRIES} 次），请重新规划。"
        task.retry_count = retry_count + 1
        task.status = "pending"
        task.error_message = ""
        task.started_at = None
        task.completed_at = None
        db.commit()
        emit("task_retry", {
            "task_item_id": task.id,
            "task_id": task.task_id,
            "retry_count": task.retry_count,
        })
        _clear_child_tasks_for_retry(parent=task, db=db, emit=emit)

    # 4. 校验依赖
    depends_on_raw = task.depends_on or ""
    deps = [d.strip() for d in depends_on_raw.split(",") if d.strip()]
    if deps:
        dep_tasks = (
            db.query(TaskItem)
            .filter_by(session_id=task.session_id)
            .filter(TaskItem.task_id.in_(deps))
            .all()
        )
        # 构建 dep_map：当同一 session 中存在多条同名 task_id 时，
        # 优先保留 completed 状态，避免旧 todolist 的 pending 记录覆盖已完成的记录。
        dep_map: dict[str, str] = {}
        STATUS_PRIORITY = {"completed": 3, "skipped": 2, "failed": 1, "in_progress": 0, "pending": -1}
        for t in dep_tasks:
            existing = dep_map.get(t.task_id)
            if existing is None or STATUS_PRIORITY.get(t.status, -1) > STATUS_PRIORITY.get(existing, -1):
                dep_map[t.task_id] = t.status
        unmet = [d for d in deps if dep_map.get(d) != "completed"]
        if unmet:
            return (
                f"任务 {task.task_id} 的依赖未满足："
                f"{', '.join(unmet)} 尚未完成。"
                f"请先完成依赖任务。"
            )

    # 5. 确定 dispatch_tool（优先用显式字段，其次用 owner/task_type/文本推断）
    if agent:
        agent_key = agent.strip().lower()
        if agent_key not in AGENT_DISPATCH_MAP:
            return "无效 agent：{agent}。合法值为 outline / chapter / evaluation。".format(agent=agent)
        dispatch_tool = AGENT_DISPATCH_MAP[agent_key]
    else:
        dispatch_tool = infer_dispatch_tool(task)
    if dispatch_tool and dispatch_tool != "none":
        task.dispatch_tool = dispatch_tool
        if task.owner in ("user", "supervisor", "", None):
            task.owner = DISPATCH_OWNER_MAP.get(dispatch_tool, task.owner)

    # 6. 不自动执行的任务
    if dispatch_tool in ("", "none"):
        return (
            f"任务 {task.task_id}（负责人：{task.owner}）不可自动执行，"
            f"需要{'用户输入' if task.owner == 'user' else '手动处理'}。"
        )

    # 7. 设置 in_progress
    set_task_status(task=task, status="in_progress", db=db, emit=emit)

    # 注入 task_item_id 到 config，让 dispatch 工具在设置 active_child 时带上
    if "configurable" not in (config or {}):
        config = {"configurable": {}}
    config["configurable"]["current_task_item_id"] = task.id
    config["configurable"]["todo_harness_bypass"] = True

    # 8. 派发子 Agent
    session_id = (config or {}).get("configurable", {}).get("supervisor_session_id")

    try:
        result_text = await _dispatch_by_tool(
            dispatch_tool=dispatch_tool,
            task=task,
            db=db,
            config=config,
        )
    except Exception as exc:
        logger.exception("execute_todo_task dispatch failed: %s", exc)
        finalize_open_child_tasks(
            parent=task,
            final_status="failed",
            db=db,
            emit=emit,
            error_message=str(exc),
        )
        set_task_status(
            task=task, status="failed", db=db, emit=emit,
            error_message=str(exc),
        )
        digest = build_subtask_digest(parent=task, db=db)
        if digest:
            task.result_summary = digest
            db.commit()
        return f"任务 {task.task_id} 执行失败：{exc}" + (f"\n{digest}" if digest else "")

    dispatch_result = _parse_dispatch_result(result_text)
    result_message = _dispatch_result_message(dispatch_result, result_text)
    if _is_failed_dispatch_result(result_text, dispatch_result):
        finalize_open_child_tasks(
            parent=task,
            final_status="failed",
            db=db,
            emit=emit,
            result_summary=result_message if result_message else "",
            error_message=result_message if result_message else "子 Agent 未完成任务",
        )
        subtask_digest = build_subtask_digest(parent=task, db=db)
        summary = _compose_task_summary(
            result_message=result_message if result_message else "子 Agent 未完成任务",
            dispatch_result=dispatch_result,
            subtask_digest=subtask_digest,
        )
        set_task_status(
            task=task,
            status="failed",
            db=db,
            emit=emit,
            result_summary=summary,
            error_message=result_message if result_message else "子 Agent 未完成任务",
        )
        return f"任务 {task.task_id} 执行失败：{result_message}" + (f"\n{subtask_digest}" if subtask_digest else "")

    # 9. 检查 session 是否进入 waiting
    if session_id:
        from app.models.agent_model import SupervisorSession
        session = db.query(SupervisorSession).filter_by(id=session_id).first()
        if session and session.status == "waiting" and session.active_child:
            # 任务保持 in_progress，等待用户确认
            return (
                f"任务 {task.task_id}（{task.task_description}）"
                f"已派发子 Agent，等待用户确认。"
            )

    # 10. 设置 completed
    finalize_open_child_tasks(
        parent=task,
        final_status="completed",
        db=db,
        emit=emit,
        result_summary="父任务已完成，子任务自动收敛为完成。",
    )
    subtask_digest = build_subtask_digest(parent=task, db=db)
    summary = _compose_task_summary(
        result_message=result_message if result_message else "",
        dispatch_result=dispatch_result,
        subtask_digest=subtask_digest,
    )
    set_task_status(
        task=task, status="completed", db=db, emit=emit,
        result_summary=summary,
    )

    return (
        f"任务 {task.task_id}（{task.task_description}）执行完成。\n"
        f"子 Agent 返回：{result_message}"
        + (f"\n{_report_digest(dispatch_result)}" if _report_digest(dispatch_result) else "")
        + (f"\n{subtask_digest}" if subtask_digest else "")
    )


def _parse_dispatch_result(result_text: str | None) -> dict | None:
    """Parse structured dispatch result JSON when available.

    Dispatch tools may return JSON with ok/status/message. Older tools still
    return natural language; those continue through the legacy text fallback.
    """
    text = (result_text or "").strip()
    if not text or not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if "ok" not in data and "status" not in data:
        return None
    return data


def _dispatch_result_message(dispatch_result: dict | None, result_text: str | None) -> str:
    if not dispatch_result:
        return result_text or ""
    message = dispatch_result.get("message")
    if message:
        return str(message)
    error = dispatch_result.get("error")
    if isinstance(error, dict):
        return str(error.get("detail") or error.get("code") or "")
    if error:
        return str(error)
    return result_text or ""


def _is_failed_dispatch_result(result_text: str | None, dispatch_result: dict | None = None) -> bool:
    if dispatch_result is not None:
        ok = dispatch_result.get("ok")
        status = str(dispatch_result.get("status") or "").lower()
        if ok is True or status in {"completed", "success", "waiting"}:
            return False
        if ok is False or status in {"failed", "error", "rejected"}:
            return True
        return False

    text = (result_text or "").strip()
    if not text:
        return True

    success_markers = (
        "执行完成",
        "写作完成",
        "修改已完成",
        "编辑已完成",
        "已完成",
        "已保存",
        "已同步章节元数据",
        "章节元数据稍后可重新同步",
        "评估完成",
        "大纲创建成功",
        "大纲变更建议已生成",
    )
    if any(marker in text for marker in success_markers):
        return False

    failure_prefixes = (
        "失败",
        "生成正文失败",
        "保存章节失败",
        "任务执行失败",
        "业务规则校验未通过",
        "工具策略拦截",
        "不可自动执行",
        "无法执行",
        "当前会话尚未绑定作品",
        "当前没有活跃的会话",
        "需要用户",
        "请先",
    )
    return text.startswith(failure_prefixes)


def _agent_task_json(
    *,
    ok: bool,
    status: str,
    tool: str,
    action: str,
    message: str,
    error: dict | None = None,
    payload: dict | None = None,
    report: dict | None = None,
) -> str:
    return json.dumps(
        {
            "ok": ok,
            "status": status,
            "tool": tool,
            "action": action,
            "message": message,
            "error": error,
            "payload": payload or {},
            "report": report,
        },
        ensure_ascii=False,
    )


async def _run_outline_task(
    *,
    instruction: str,
    work_id: str | None,
    db: Session,
    config: RunnableConfig,
    configurable: dict,
) -> str:
    from app.models.agent_model import SupervisorSession
    from app.models.message_model import Message
    from app.services.supervisor.outline_agent import OutlineAgent
    from app.services.supervisor.tools import _store_memory

    emit = configurable.get("emit", lambda event, data: None)
    db_lock = configurable.get("db_lock")
    session_id = configurable.get("supervisor_session_id")
    session = None
    if session_id:
        session = db.query(SupervisorSession).filter_by(id=session_id).first()
        if not work_id and session and session.work_id:
            work_id = session.work_id

    if session and session.work_id and work_id and work_id != session.work_id:
        message = (
            "无法执行：当前操作目标与会话绑定作品不一致。"
            "请使用当前会话继续操作，或开启新会话后再操作其他作品。"
        )
        return _agent_task_json(
            ok=False,
            status="rejected",
            tool="outline_agent",
            action="outline_task",
            message=message,
            error={"code": "WORK_BINDING_MISMATCH", "detail": message},
        )

    agent = OutlineAgent(emit=emit, user_id=configurable.get("user_id"))
    memories: dict[str, list[str]] = configurable.get("sub_agent_memories", {})

    if not work_id:
        try:
            result = await agent.create_outline(
                idea=instruction,
                tags=[],
                db=db,
                db_lock=db_lock,
                base_configurable=configurable,
            )
        except Exception as exc:
            logger.exception("outline_agent create failed: %s", exc)
            message = f"创建大纲失败：{exc!r}"
            return _agent_task_json(
                ok=False,
                status="failed",
                tool="outline_agent",
                action="outline_create",
                message=message,
                error={"code": "OUTLINE_AGENT_ERROR", "detail": repr(exc)},
            )

        if result.get("error"):
            message = f"创建大纲失败：{result['error']}"
            return _agent_task_json(
                ok=False,
                status="failed",
                tool="outline_agent",
                action="outline_create",
                message=message,
                error={"code": "OUTLINE_CREATE_FAILED", "detail": message},
            )

        created_work_id = result.get("work_id")
        if created_work_id and session_id:
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

        _store_memory(memories, "outline", f"创建大纲：{result.get('title', '')}")
        message = f"大纲创建成功。作品「{result.get('title', '')}」"
        return _agent_task_json(
            ok=True,
            status="completed",
            tool="outline_agent",
            action="outline_create",
            message=message,
            payload=result,
            report={
                "status": "completed",
                "summary": message,
                "actions": ["创建作品大纲"],
                "artifacts": [f"作品：{result.get('title', '')}", f"work_id={created_work_id}"],
                "issues": [],
                "next_suggestions": [],
            },
        )

    auto_mode = bool(configurable.get("auto_mode", False))
    try:
        result = await agent.edit_outline(
            work_id=work_id,
            message=instruction,
            history=memories.get("outline", []),
            db=db,
            auto_mode=auto_mode,
            db_lock=db_lock,
            base_configurable=configurable,
        )
    except Exception as exc:
        logger.exception("outline_agent edit failed: %s", exc)
        message = f"编辑大纲失败：{exc!r}"
        return _agent_task_json(
            ok=False,
            status="failed",
            tool="outline_agent",
            action="outline_edit",
            message=message,
            error={"code": "OUTLINE_AGENT_ERROR", "detail": repr(exc)},
        )

    if result.get("error"):
        message = f"编辑大纲失败：{result.get('message', result.get('error', '未知错误'))}"
        return _agent_task_json(
            ok=False,
            status="failed",
            tool="outline_agent",
            action="outline_edit",
            message=message,
            error={"code": "OUTLINE_EDIT_FAILED", "detail": message},
        )

    _store_memory(
        memories,
        "outline",
        f"编辑大纲 work_id={work_id}：{result.get('message', '')}",
    )

    if auto_mode:
        message = result.get("message", "大纲编辑已完成。")
        return _agent_task_json(
            ok=True,
            status="completed",
            tool="outline_agent",
            action="outline_edit",
            message=message,
            payload=result,
            report={
                "status": "completed",
                "summary": message,
                "actions": ["编辑大纲"],
                "artifacts": [],
                "issues": [],
                "next_suggestions": [],
            },
        )

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

    message = (
        f"大纲变更建议已生成"
        f"（大纲 +{outline_summary.get('total_added', 0)}/~{outline_summary.get('total_modified', 0)}/-{outline_summary.get('total_removed', 0)}"
        f"，角色 +{character_summary.get('total_added', 0)}/~{character_summary.get('total_modified', 0)}/-{character_summary.get('total_removed', 0)}"
        f"）。"
        f"执行了 {len(ops)} 项操作。请等待用户确认。"
    )
    return _agent_task_json(
        ok=True,
        status="waiting",
        tool="outline_agent",
        action="outline_edit",
        message=message,
        payload=result,
        report={
            "status": "waiting",
            "summary": message,
            "actions": ["生成大纲变更建议"],
            "artifacts": [f"操作数：{len(ops)}"],
            "issues": ["等待用户确认"],
            "next_suggestions": ["用户确认后继续执行"],
        },
    )


async def _run_evaluation_task(
    *,
    instruction: str,
    work_id: str | None,
    db: Session,
    config: RunnableConfig,
    configurable: dict,
) -> str:
    from app.services.evaluation_agent import EvaluationAgent
    from app.services.supervisor.tools import _store_memory

    if not work_id:
        message = "当前会话尚未绑定作品。"
        return _agent_task_json(
            ok=False,
            status="rejected",
            tool="evaluation_agent",
            action="evaluation_task",
            message=message,
            error={"code": "WORK_NOT_BOUND", "detail": message},
        )

    emit = configurable.get("emit", lambda event, data: None)
    configurable = dict(configurable)
    configurable["emit"] = emit
    emit("stage_start", {"stage": "evaluation", "label": "章节评估"})

    memories: dict[str, list[str]] = configurable.get("sub_agent_memories", {})
    agent = EvaluationAgent()
    try:
        title, editor_text, reader_text, sync_text = await agent.evaluate_chapter(
            db=db,
            work_id=work_id,
            chapter_number=None,
            user_message=instruction,
            history=memories.get("evaluation", []),
            base_configurable=configurable,
        )
    except Exception as exc:
        logger.exception("evaluation_agent direct execution failed: %s", exc)
        message = f"评估失败：{exc!r}"
        return _agent_task_json(
            ok=False,
            status="failed",
            tool="evaluation_agent",
            action="evaluation_task",
            message=message,
            error={"code": "EVALUATION_AGENT_ERROR", "detail": repr(exc)},
        )

    summary = (
        f"「{title}」评估完成。"
        f"【编辑视角】{editor_text}"
        f"【读者视角】{reader_text}"
        f"【同步性】{sync_text}"
    )
    _store_memory(memories, "evaluation", summary)
    emit(
        "evaluation_done",
        {
            "chapter_title": title,
            "editor": editor_text,
            "reader": reader_text,
            "sync": sync_text,
        },
    )
    return _agent_task_json(
        ok=True,
        status="completed",
        tool="evaluation_agent",
        action="evaluation_task",
        message=summary,
        payload={
            "title": title,
            "editor": editor_text,
            "reader": reader_text,
            "sync": sync_text,
        },
        report={
            "status": "completed",
            "summary": f"「{title}」评估完成。",
            "actions": ["完成章节质量评估"],
            "artifacts": [f"编辑视角：{editor_text}", f"读者视角：{reader_text}", f"同步性：{sync_text}"],
            "issues": [],
            "next_suggestions": [],
        },
    )


async def _dispatch_by_tool(
    *,
    dispatch_tool: str,
    task: TaskItem,
    db: Session,
    config: RunnableConfig,
) -> str:
    """根据 dispatch_tool 路由到对应子 Agent（todolist 主链路不经 dispatch_* 工具）。"""
    instruction = getattr(task, "instruction", "") or task.task_description
    configurable = (config or {}).get("configurable", {})
    session_id = configurable.get("supervisor_session_id")

    work_id = None
    if session_id:
        from app.models.agent_model import SupervisorSession
        session = db.query(SupervisorSession).filter_by(id=session_id).first()
        if session:
            work_id = session.work_id

    if dispatch_tool == "dispatch_outline":
        return await _run_outline_task(
            instruction=instruction,
            work_id=work_id,
            db=db,
            config=config,
            configurable=configurable,
        )
    elif dispatch_tool == "dispatch_chapter":
        from app.services.supervisor.chapter_agent import ChapterAgent

        if not work_id:
            return json.dumps(
                {
                    "ok": False,
                    "status": "rejected",
                    "tool": "chapter_agent",
                    "action": "chapter_task",
                    "message": "当前会话尚未绑定作品。",
                    "error": {"code": "WORK_NOT_BOUND", "detail": "当前会话尚未绑定作品。"},
                    "payload": {},
                },
                ensure_ascii=False,
            )

        emit = configurable.get("emit", lambda event, data: None)
        agent = ChapterAgent(emit=emit)
        try:
            result = await agent.run(
                work_id=work_id,
                user_message=instruction,
                db=db,
                chapter_number=None,
                is_new_chapter=None,
                auto_mode=bool(configurable.get("auto_mode", True)),
                db_lock=configurable.get("db_lock"),
                base_configurable=configurable,
            )
        except Exception as exc:
            logger.exception("chapter_agent direct execution failed: %s", exc)
            return json.dumps(
                {
                    "ok": False,
                    "status": "failed",
                    "tool": "chapter_agent",
                    "action": "chapter_task",
                    "message": f"章节任务执行失败：{exc!r}",
                    "error": {"code": "CHAPTER_AGENT_ERROR", "detail": repr(exc)},
                    "payload": {},
                },
                ensure_ascii=False,
            )

        message = str((result or {}).get("message") or "章节任务已完成。")
        report = (result or {}).get("report")
        failed = _is_failed_dispatch_result(message)
        return json.dumps(
            {
                "ok": not failed,
                "status": "failed" if failed else "completed",
                "tool": "chapter_agent",
                "action": "chapter_task",
                "message": message,
                "error": {"code": "CHAPTER_AGENT_REPORTED_FAILURE", "detail": message} if failed else None,
                "payload": result or {},
                "report": report if isinstance(report, dict) else None,
            },
            ensure_ascii=False,
        )
    elif dispatch_tool == "dispatch_evaluation":
        return await _run_evaluation_task(
            instruction=instruction,
            work_id=work_id,
            db=db,
            config=config,
            configurable=configurable,
        )
    else:
        raise ValueError(f"未知的执行工具：{dispatch_tool}，任务不可自动执行")


# ── Reconciliation ──


def reconcile_stale_tasks(
    *,
    session_id: str,
    db: Session,
    stale_threshold_minutes: int = 30,
    emit: Callable[[str, dict], None] | None = None,
) -> dict:
    """检测并修复不一致的任务状态

    规则：
    - in_progress 且 started_at 超过阈值、session 不在 waiting 状态 → 标记为 failed
    - 其他状态不受影响
    """
    from app.models.agent_model import SupervisorSession

    session = db.query(SupervisorSession).filter_by(id=session_id).first()
    is_waiting = session and session.status == "waiting" and session.active_child

    tasks = (
        db.query(TaskItem)
        .filter_by(session_id=session_id)
        .all()
    )

    now = _utcnow()
    threshold = timedelta(minutes=stale_threshold_minutes)
    reconciled = 0

    for task in tasks:
        if task.status != "in_progress":
            continue
        if is_waiting:
            continue
        if task.started_at and (now - task.started_at) > threshold:
            task.status = "failed"
            task.error_message = (
                f"任务超时未完成（started_at={task.started_at.isoformat()}），"
                f"已由 reconciliation 自动标记为 failed。"
            )
            task.completed_at = now
            reconciled += 1
            if emit:
                emit("task_status_updated", {
                    "task_item_id": task.id,
                    "task_id": task.task_id,
                    "old_status": "in_progress",
                    "new_status": "failed",
                    "result_summary": "",
                    "error_message": task.error_message,
                })

    if reconciled > 0:
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

    return {"reconciled": reconciled}
