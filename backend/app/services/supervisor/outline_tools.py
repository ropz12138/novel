"""OutlineAgent 工具集

大纲子 Agent 可调用的工具，封装大纲读取、角色查询、大纲生成/编辑和 diff 计算。
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Callable

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── Tool input schemas ──


class ReadOutlineInput(BaseModel):
    pass


class QueryOutlineCharactersInput(BaseModel):
    pass


class QueryOutlineRelatedChaptersInput(BaseModel):
    outline_queries: list[str] = Field(default_factory=list, description="大纲片段查询词列表：可传多个节点ID或关键词")
    outline_query: str | None = Field(default=None, description="兼容字段：单个查询词")
    chapter_start: int | None = Field(default=None, description="可选：起始章节号")
    chapter_end: int | None = Field(default=None, description="可选：结束章节号")
    chapter_limit: int = Field(default=10, ge=1, le=100, description="返回章节上限")


class GenerateOutlineInput(BaseModel):
    idea: str = Field(
        description=(
            "故事创意与用户全部硬性约束（须原文写入）："
            "章节规模、主线 timeline 节点数、支线 branches 数、伏笔 foreshadowing 数、角色 characters 数量等。"
            "不要自行扩写题材或增加用户未要求的复杂度。"
        ),
    )
    tags: list[str] = Field(default_factory=list, description="题材标签列表，如「科幻」「悬疑」")


class GenerateMacroOutlineInput(BaseModel):
    idea: str = Field(
        description=(
            "故事创意与用户全部硬性约束（须原文写入）："
            "宏观阶段数、核心角色数等。"
            "不要自行扩写题材或增加用户未要求的复杂度。"
        ),
    )
    tags: list[str] = Field(default_factory=list, description="题材标签列表，如「科幻」「悬疑」")


class GenerateMesoOutlineInput(BaseModel):
    idea: str = Field(
        description=(
            "用户需求补充（可选）：对中纲生成的额外要求。"
        ),
    )


class GenerateMicroOutlineInput(BaseModel):
    idea: str = Field(
        description=(
            "用户需求补充（可选）：对小纲生成的额外要求。"
        ),
    )


class GenerateCharacterDetailsInput(BaseModel):
    idea: str = Field(
        default="",
        description="用户需求补充（可选）：对角色详情生成的额外要求。",
    )


class EditCharacterDetailsInput(BaseModel):
    suggestion: str = Field(description="修改建议（自然语言）")
    character_name: str = Field(default="", description="可选：指定编辑某个角色，留空表示编辑全部角色")


class EditOutlineInput(BaseModel):
    message: str = Field(description="编辑指令：用户想要对大纲做什么")


class EditOutlineBySuggestionInput(BaseModel):
    suggestion: str = Field(description="修改建议（自然语言）")
    context_note: str = Field(default="", description="可选：补充上下文（自然语言）")


class ReplaceOutlineFieldInput(BaseModel):
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
    updates: list[ReplaceOutlineFieldItem] = Field(default_factory=list, description="批量替换项")


class InsertOutlineItemInput(BaseModel):
    path: str = Field(description="目标列表路径：timeline/branches/foreshadowing")
    mode: str = Field(description="插入模式：append/after_id/before_id/index")
    anchor_id: str = Field(default="", description="锚点ID（after_id/before_id 时使用）")
    index: int = Field(default=-1, description="插入位置（index 模式时使用）")
    item: dict = Field(description="插入对象")
    op_id: str = Field(default="", description="可选：操作ID，便于审计")
    reason: str = Field(default="", description="可选：变更原因")


class DeleteOutlineItemInput(BaseModel):
    path: str = Field(description="目标列表路径：timeline/branches/foreshadowing")
    match_field: str = Field(description="匹配字段，如 id/name")
    match_value: str = Field(description="匹配值")
    op_id: str = Field(default="", description="可选：操作ID，便于审计")
    reason: str = Field(default="", description="可选：变更原因")


class ReplaceCharacterFieldInput(BaseModel):
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
    first_appearance_stage: str = Field(default="M1", description="首次出场阶段（中纲阶段ID）")
    notes: str = Field(default="", description="备注")


class DeleteCharacterInput(BaseModel):
    name: str = Field(description="要删除的角色名")


class CommitOrRollbackInput(BaseModel):
    action: str = Field(description="操作：commit 或 rollback")


# ── 三层大纲架构输入模型 ──


class ReadMacroOutlineInput(BaseModel):
    pass


class ReadMesoOutlineInput(BaseModel):
    pass


class ReadMicroOutlineInput(BaseModel):
    pass


class EditMacroOutlineInput(BaseModel):
    suggestion: str = Field(description="修改建议（自然语言）")
    context_note: str = Field(default="", description="可选：补充上下文（自然语言）")


class EditMesoOutlineInput(BaseModel):
    suggestion: str = Field(description="修改建议（自然语言）")
    context_note: str = Field(default="", description="可选：补充上下文（自然语言）")


class EditMicroOutlineInput(BaseModel):
    suggestion: str = Field(description="修改建议（自然语言）")
    context_note: str = Field(default="", description="可选：补充上下文（自然语言）")


class AddMacroPhaseInput(BaseModel):
    phase_id: str = Field(description="阶段ID，如 P1、P2")
    name: str = Field(description="阶段名称")
    goal: str = Field(description="阶段目标")
    core_setting: str = Field(description="核心设定")
    ending_direction: str = Field(default="", description="结局方向（可选）")
    chapter_range: list[int] = Field(default_factory=lambda: [1, 50], description="预计章节范围")


class AddMesoStageInput(BaseModel):
    stage_id: str = Field(description="阶段ID，如 M1、M2")
    macro_phase_id: str = Field(description="关联的大纲阶段ID")
    name: str = Field(description="阶段名称")
    type: str = Field(description="类型：副本/地图/案件/赛事/战争/感情阶段/商业阶段")
    cause: str = Field(description="起因")
    conflict: str = Field(description="冲突")
    key_characters: list[str] = Field(default_factory=list, description="关键人物")
    twist: str = Field(default="", description="反转")
    climax: str = Field(default="", description="高潮")
    reward: str = Field(default="", description="收益")
    chapter_range: list[int] = Field(default_factory=lambda: [1, 10], description="预计章节范围")


class AddMicroSceneInput(BaseModel):
    scene_id: str = Field(description="场景ID，如 S1、S2")
    meso_stage_id: str = Field(description="关联的中纲阶段ID")
    chapter_number: int = Field(description="章节号")
    scene_number: int = Field(default=1, description="场景号")
    characters: list[str] = Field(default_factory=list, description="出场人物")
    location: str = Field(default="", description="地点")
    conflict: str = Field(default="", description="冲突")
    info_points: list[str] = Field(default_factory=list, description="信息点")
    emotion_points: list[str] = Field(default_factory=list, description="爽点/笑点/情绪点")
    hook: str = Field(default="", description="结尾钩子")


class ChildTodoItemInput(BaseModel):
    id: str = Field(default="", description="可选子任务ID，如 T1.1；不传则自动生成")
    task: str = Field(description="子任务描述")
    depends_on: list[str] = Field(default_factory=list, description="依赖的子任务ID")
    done_criteria: str = Field(default="", description="完成判定标准")


class CreateChildTodolistInput(BaseModel):
    """为当前 Supervisor 父任务创建子任务清单。

    字段名必须是 items（不是 todos）。
    值必须是对象数组（不是 JSON 字符串）。
    """
    items: list[ChildTodoItemInput] = Field(
        description="当前父任务下的子任务列表。注意：字段名必须是 items，不能是 todos；值必须是对象数组，不能是 JSON 字符串。"
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_input(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # 兼容模型传入 todos 而非 items
        if "items" not in data and "todos" in data:
            data["items"] = data.pop("todos")
        # 兼容模型传入 JSON 字符串而非数组
        raw = data.get("items")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    data["items"] = parsed
            except (json.JSONDecodeError, TypeError):
                pass
        return data


class ReadChildTodolistInput(BaseModel):
    pass


class UpdateChildTaskStatusInput(BaseModel):
    task_identifier: str = Field(description="子任务ID或数据库ID，如 T1.1")
    status: str = Field(description="新状态：pending / in_progress / completed / skipped / failed")
    result_summary: str = Field(default="", description="可选：结果摘要")
    error_message: str = Field(default="", description="可选：错误说明")


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


def _get_work_id(config: RunnableConfig) -> str:
    configurable = config.get("configurable", {})
    work_id = configurable.get("work_id")
    if work_id is not None and work_id != "":
        return work_id
    session_id = configurable.get("supervisor_session_id")
    if session_id:
        db = configurable.get("db")
        if db:
            from app.models.agent_model import SupervisorSession
            session = db.query(SupervisorSession).filter_by(id=session_id).first()
            if session and session.work_id:
                return session.work_id
    # 尝试从当前用户最近的作品中获取
    db = configurable.get("db")
    user_id = configurable.get("user_id")
    if db and user_id:
        from app.models.work_model import Work
        work = db.query(Work).filter_by(user_id=user_id).order_by(Work.updated_at.desc()).first()
        if work:
            return work.id
    raise ValueError("work_id 未在 configurable 中提供，请先生成大纲（Macro Outline）以创建作品。")


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


# ── LLM 调用 + 入库 辅助函数 ──


def _emit_outline_done(
    emit,
    *,
    work_id: str,
    title: str,
    stage: str | None = None,
) -> None:
    """发送 outline_done SSE 事件，统一携带 title，stage 表示分步完成类型。"""
    payload: dict[str, str] = {"work_id": work_id, "title": title}
    if stage:
        payload["stage"] = stage
    emit("outline_done", payload)


def _emit_outline_stage_error(
    emit,
    *,
    work_id: str,
    title: str,
    stage: str,
    message: str,
) -> None:
    """发送 outline_stage_error SSE 事件，通知前端结束对应阶段的 loading 状态。"""
    emit("outline_stage_error", {
        "work_id": work_id,
        "title": title,
        "stage": stage,
        "message": message,
    })


def _extract_tool_call_args(ai_msg, tool_name: str) -> dict | None:
    """从 LLM 响应中提取指定工具的 tool_call args。"""
    tool_calls = getattr(ai_msg, "tool_calls", None) or []
    for tc in tool_calls:
        if tc.get("name") == tool_name:
            args = tc.get("args") or {}
            if isinstance(args, dict):
                return args
    return None


def _try_unwrap_nested_args(args: dict, submit_tool) -> dict:
    """If LLM wrapped all args under a single extra key, unwrap to the inner dict.

    LLM sometimes outputs {"macro_outline": {"story": ..., "macro_phases": ...}}
    instead of {"story": ..., "macro_phases": ...}. This function detects that
    pattern by checking if args has exactly one key whose value is a dict that
    contains at least one field from the submit_tool's schema.
    """
    if len(args) != 1:
        return args
    single_value = next(iter(args.values()))
    if not isinstance(single_value, dict) or not single_value:
        return args
    schema = getattr(submit_tool, "args_schema", None)
    if schema is None:
        return args
    expected_fields = set(getattr(schema, "model_fields", {}).keys())
    if not expected_fields:
        return args
    overlap = expected_fields & set(single_value.keys())
    if overlap:
        return single_value
    return args


async def _invoke_and_persist(
    *,
    prompt: str,
    submit_tool: StructuredTool,
    tool_name: str,
    max_retries: int = 3,
    field_name: str | None = None,
    stream_event: str = "outline_stream",
    emit_fn: Callable | None = None,
) -> dict:
    """调用 LLM 生成结构化大纲数据，解析 tool_call 并执行 submit 工具入库。

    Args:
        prompt: 发给 LLM 的 prompt 文本
        submit_tool: StructuredTool，LLM 需要调用的 submit 工具
        tool_name: submit 工具名称，如 "submit_macro_outline"
        max_retries: 最大重试次数
        field_name: 期望从 args 中提取的字段名，None 表示返回整个 args
        stream_event: 流式推送的 SSE 事件名
        emit_fn: 可选的 emit 函数，用于推送流式分片

    Returns:
        LLM tool_call 的 args 字典（或指定字段的值）
    """
    from langchain_core.messages import AIMessageChunk, HumanMessage

    from app.services.supervisor.sub_agent_base import (
        chunk_to_ai_message,
        emit_llm_stream_deltas,
        get_llm,
    )

    llm = get_llm(temperature=0.7, streaming=True)
    llm_with_tools = llm.bind_tools([submit_tool], max_tokens=131072)

    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        retry_prompt = prompt
        if attempt > 1:
            retry_prompt = (
                f"{prompt}\n\n"
                "【强约束】你上一次输出未被系统识别。"
                "这一次只允许输出工具调用，不允许解释性文字。"
                f"必须且只调用 {tool_name}，确保输出合法 JSON。"
            )
        try:
            aggregated: AIMessageChunk | None = None
            async for chunk in llm_with_tools.astream([HumanMessage(content=retry_prompt)]):
                aggregated = chunk if aggregated is None else aggregated + chunk
                if emit_fn:
                    emit_llm_stream_deltas(emit_fn, stream_event, chunk)
            if aggregated is None:
                last_exc = RuntimeError("LLM returned no chunks")
                continue
            msg = chunk_to_ai_message(aggregated)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "_invoke_and_persist llm invoke failed tool=%s attempt=%s/%s err=%s",
                tool_name, attempt, max_retries, exc,
            )
            continue

        args = _extract_tool_call_args(msg, tool_name)
        if args is None:
            text = getattr(msg, "content", "") or ""
            logger.warning(
                "_invoke_and_persist no tool_call tool=%s attempt=%s text=%r",
                tool_name, attempt, text[:200],
            )
            last_exc = ValueError(f"LLM did not call {tool_name}")
            continue

        # Unwrap: LLM sometimes nests all args under a single extra key
        # (e.g. {"macro_outline": {real data}} instead of {real data}).
        # If args has exactly one key whose value is a dict containing
        # fields that the submit_tool schema expects, unwrap it.
        unwrapped = _try_unwrap_nested_args(args, submit_tool)
        if unwrapped is not args:
            logger.info(
                "_invoke_and_persist unwrapped nested args tool=%s old_keys=%s new_keys=%s",
                tool_name,
                list(args.keys()),
                list(unwrapped.keys()),
            )
        args = unwrapped

        # 执行 submit 工具入库
        try:
            submit_tool.func(**args)
        except Exception as exc:
            logger.warning(
                "_invoke_and_persist submit failed tool=%s err=%s",
                tool_name, exc,
            )
            last_exc = exc
            continue

        if field_name is not None:
            if field_name not in args:
                last_exc = ValueError(f"{tool_name} missing field: {field_name}")
                continue
            return args[field_name]
        return args

    assert last_exc is not None
    raise last_exc


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


@tool(args_schema=CreateChildTodolistInput)
def create_child_todolist(items: list[ChildTodoItemInput], config: RunnableConfig) -> str:
    """为当前 Supervisor 父任务创建子任务清单。只维护当前任务内部进度。
    参数 items 必须是对象数组，字段名必须是 items（不能是 todos）。
    """
    from app.services.supervisor.todo_harness import create_child_todolist as _create_child_todolist

    db = _get_db(config)
    emit = _get_emit(config)
    payload = [item.model_dump() if hasattr(item, "model_dump") else dict(item) for item in items]
    with _with_lock(config):
        return _create_child_todolist(items=payload, db=db, emit=emit, config=config)


@tool(args_schema=ReadChildTodolistInput)
def read_child_todolist(config: RunnableConfig) -> str:
    """读取当前 Supervisor 父任务下的子任务清单。"""
    from app.services.supervisor.todo_harness import read_child_todolist as _read_child_todolist

    db = _get_db(config)
    with _with_lock(config):
        return _read_child_todolist(db=db, config=config)


@tool(args_schema=UpdateChildTaskStatusInput)
def update_child_task_status(
    task_identifier: str,
    status: str,
    result_summary: str = "",
    error_message: str = "",
    config: RunnableConfig = None,
) -> str:
    """更新当前父任务下某个子任务的状态。"""
    from app.services.supervisor.todo_harness import update_child_task_status as _update_child_task_status

    db = _get_db(config)
    emit = _get_emit(config)
    with _with_lock(config):
        return _update_child_task_status(
            task_identifier=task_identifier,
            status=status,
            db=db,
            emit=emit,
            config=config,
            result_summary=result_summary,
            error_message=error_message,
        )


@tool(args_schema=ReadOutlineInput)
def read_outline(config: RunnableConfig, work_id: str | None = None) -> str:
    """读取作品当前的完整大纲信息。编辑大纲前必须先读取现有数据。"""
    from app.models.work_model import Work

    db = _get_db(config)
    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    outline = work.outline_tree or {}
    story = outline.get("story", {})
    macro_phases = outline.get("outline", {}).get("macro_phases", [])
    meso_stages = outline.get("meso", {}).get("meso_stages", [])
    foreshadowing = outline.get("foreshadowing", [])

    import json
    parts = [
        f"标题：{work.title}",
        f"类型：{story.get('genre', '未知')}",
        f"卷：{story.get('volume', '未知')}",
        f"宏观阶段数：{len(macro_phases)}",
        f"中纲阶段数：{len(meso_stages)}",
        f"伏笔数：{len(foreshadowing)}",
    ]
    if story.get("synopsis"):
        parts.append(f"简介：{story['synopsis']}")
    parts.append(f"\n完整大纲：\n{json.dumps(outline, ensure_ascii=False, indent=2)}")

    emit("query_result", {"source": "大纲读取", "summary": f"宏观阶段 {len(macro_phases)}，中纲阶段 {len(meso_stages)}"})
    return "\n".join(parts)


@tool(args_schema=ReadMacroOutlineInput)
def read_macro_outline(config: RunnableConfig, work_id: str | None = None) -> str:
    """读取大纲（Macro Outline）：包含 story、macro_phases、core_characters、ending。"""
    from app.models.work_model import Work

    db = _get_db(config)
    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    outline = work.outline_tree or {}
    story = outline.get("story", {})
    macro_data = outline.get("outline", {})
    macro_phases = macro_data.get("macro_phases", [])
    core_characters = macro_data.get("core_characters", [])
    ending = macro_data.get("ending", {})

    import json
    parts = [
        f"标题：{work.title}",
        f"类型：{story.get('genre', '未知')}",
        f"卷：{story.get('volume', '未知')}",
        f"宏观阶段数：{len(macro_phases)}",
        f"核心角色数：{len(core_characters)}",
    ]
    if story.get("synopsis"):
        parts.append(f"简介：{story['synopsis']}")
    if macro_phases:
        parts.append(f"\n宏观阶段：")
        for phase in macro_phases:
            parts.append(f"  - {phase.get('id', '')}: {phase.get('name', '')}（第{phase.get('chapter_range', [0,0])[0]}-{phase.get('chapter_range', [0,0])[1]}章）")
            parts.append(f"    目标：{phase.get('goal', '')}")
            parts.append(f"    核心设定：{phase.get('core_setting', '')}")
    if core_characters:
        parts.append(f"\n核心角色：")
        for c in core_characters:
            parts.append(f"  - {c.get('name', '')}（{c.get('role_type', '')}）：{c.get('brief', '')}")
    if ending and ending.get("direction"):
        parts.append(f"\n结局方向：{ending.get('direction', '未设定')}")

    emit("query_result", {"source": "大纲读取", "summary": f"宏观阶段 {len(macro_phases)} 个"})
    return "\n".join(parts)


@tool(args_schema=ReadMesoOutlineInput)
def read_meso_outline(config: RunnableConfig, work_id: str | None = None) -> str:
    """读取中纲（Meso Outline）：包含 meso_stages。"""
    from app.models.work_model import Work

    db = _get_db(config)
    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    outline = work.outline_tree or {}
    meso_outline = outline.get("meso", {})
    meso_stages = meso_outline.get("meso_stages", [])

    import json
    parts = [
        f"中纲阶段数：{len(meso_stages)}",
    ]
    if meso_stages:
        parts.append(f"\n中纲阶段：")
        for stage in meso_stages:
            parts.append(f"  - {stage.get('id', '')}: {stage.get('name', '')} ({stage.get('type', '')})")
            parts.append(f"    起因：{stage.get('cause', '')}")
            parts.append(f"    冲突：{stage.get('conflict', '')}")

    emit("query_result", {"source": "中纲读取", "summary": f"中纲阶段 {len(meso_stages)} 个"})
    return "\n".join(parts)


@tool(args_schema=ReadMicroOutlineInput)
def read_micro_outline(config: RunnableConfig, work_id: str | None = None) -> str:
    """读取小纲（Micro Outline）：包含 micro_scenes。"""
    from app.models.work_model import Work

    db = _get_db(config)
    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    outline = work.outline_tree or {}
    micro_outline = outline.get("micro", {})
    micro_scenes = micro_outline.get("micro_scenes", [])

    import json
    parts = [
        f"小纲场景数：{len(micro_scenes)}",
    ]
    if micro_scenes:
        parts.append(f"\n小纲场景：")
        for scene in micro_scenes:
            parts.append(f"  - {scene.get('id', '')}: 第{scene.get('chapter_number', '?')}章 场景{scene.get('scene_number', '?')}")
            parts.append(f"    人物：{', '.join(scene.get('characters', []))}")
            parts.append(f"    地点：{scene.get('location', '')}")
            parts.append(f"    冲突：{scene.get('conflict', '')}")

    emit("query_result", {"source": "小纲读取", "summary": f"小纲场景 {len(micro_scenes)} 个"})
    return "\n".join(parts)


@tool(args_schema=QueryOutlineCharactersInput)
def query_outline_characters(config: RunnableConfig, work_id: str | None = None) -> str:
    """查询作品的所有角色设定。编辑大纲涉及角色变更时应先查询。"""
    from app.models.work_model import Character

    db = _get_db(config)
    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)

    with _with_lock(config):
        characters = db.query(Character).filter_by(work_id=work_id).order_by(
            Character.first_appearance_stage.asc(), Character.created_at.asc()
        ).all()
    if not characters:
        return "该作品暂无角色设定。"

    parts = []
    for c in characters:
        fields = [f"【{c.name}】{c.role_type}"]
        for key, label in [
            ("gender", "性别"), ("age", "年龄"), ("personality", "性格"),
            ("background", "背景"), ("current_status", "状态"),
            ("first_appearance_stage", "首次出场阶段"),
        ]:
            val = getattr(c, key, None)
            if val:
                fields.append(f"{label}：{val}")
        parts.append("，".join(fields))

    emit("query_result", {"source": "角色查询", "summary": f"共 {len(characters)} 个角色"})
    return "\n".join(parts)


@tool(args_schema=QueryOutlineRelatedChaptersInput)
def query_outline_related_chapters(
    outline_queries: list[str] | None = None,
    chapter_limit: int = 10,
    outline_query: str | None = None,
    chapter_start: int | None = None,
    chapter_end: int | None = None,
    config: RunnableConfig = None,
    work_id: str | None = None,
) -> str:
    """级联查询：先匹配大纲片段，再回查关联章节（基于 chapter_metadata）。"""
    from app.models.work_model import Chapter, ChapterMetadata, Work

    db = _get_db(config)
    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)

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
            " ".join(str(x) for x in (b.facts or [])),
        ]).lower()
        text_hits = [kw for kw in keywords if kw and kw in searchable]
        if text_hits:
            score += min(3, len(text_hits))
            reasons.append(f"命中元数据关键词: {', '.join(text_hits)}")

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
    lines = [f"查询词：{', '.join(queries)}", f"命中大纲线索：{'; '.join(outline_hits) or '无'}", "关联章节："]
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

    return f"大纲创建成功。作品「{result.get('title', '')}」"


async def _edit_outline_by_suggestion_coroutine(
    suggestion: str,
    context_note: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """单入口大纲编辑：外层只传建议，内部独立 LLM 完成具体字段修改。"""
    from app.services.work_service import WorkService

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
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


async def _generate_macro_outline_coroutine(
    idea: str,
    tags: list[str],
    config: RunnableConfig,
) -> str:
    """生成大纲（Macro Outline）：内部调用 LLM，通过 submit_macro_outline 入库。"""
    from app.models.work_model import Work
    from app.services.work_service import (
        _OUTLINE_GENERATION_CTX,
        SUBMIT_MACRO_OUTLINE_TOOL,
        _empty_outline,
    )

    db = _get_db(config)
    emit = _get_emit(config)
    user_id = config.get("configurable", {}).get("user_id")

    if not user_id:
        return _atomic_result(
            status="error",
            tool="generate_macro_outline",
            op_id="",
            message="未认证用户，无法生成大纲。",
        )

    emit("stage_start", {"stage": "macro_outline_create", "label": "生成大纲"})

    # 设置 outline ctx，使 submit 工具能入库
    token = _OUTLINE_GENERATION_CTX.set({
        "db": db,
        "user_id": user_id,
        "idea": idea,
        "tags_list": tags or [],
    })
    try:
        tags_str = "、".join(tags) if tags else "无特殊要求"
        prompt = (
            "你是网络小说策划编辑。请基于用户灵感生成大纲（Macro Outline）及中纲阶段。\n"
            f"原始用户需求（必须严格遵循）：\n"
            f"- 灵感：{idea}\n"
            f"- 标签：{tags_str}\n"
            "【JSON 约束】所有字符串值中禁止使用英文双引号，如需引用请使用中文双引号或单引号。\n"
            "大纲包含：story（标题、类型、卷名）、macro_phases（宏观阶段数组）、core_characters（核心角色简介）、meso_stages（中纲阶段数组，可选）、ending（结局方向，可选）。\n"
            "macro_phases 每个阶段需包含：id、name、goal、core_setting、chapter_range。\n"
            "core_characters 每个角色需包含：name、role_type、brief（一句话定位）。\n"
            "meso_stages 每个阶段需包含：id、macro_phase_id、name、summary、chapter_range。为每个宏观阶段生成 3-5 个中纲阶段。\n"
            "必须调用 submit_macro_outline，不要输出普通文本。"
        )

        args = await _invoke_and_persist(
            prompt=prompt,
            submit_tool=SUBMIT_MACRO_OUTLINE_TOOL,
            tool_name="submit_macro_outline",
            emit_fn=emit,
        )

        # 从 ctx 获取 work_id（submit 工具可能创建了新 Work）
        ctx = _OUTLINE_GENERATION_CTX.get()
        work_id = ctx.get("work_id", "") if ctx else ""
        title = args.get("story", {}).get("title", "未命名作品")

        _emit_outline_done(emit, work_id=work_id, title=title)

        return _atomic_result(
            status="applied",
            tool="generate_macro_outline",
            op_id="",
            message=f"大纲生成成功。作品「{title}」（ID: {work_id}）。"
                    f"宏观阶段 {len(args.get('macro_phases', []))} 个，"
                    f"核心角色 {len(args.get('core_characters', []))} 个，"
                    f"中纲阶段 {len(args.get('meso_stages', []))} 个。",
            diff={"work_id": work_id, "title": title},
        )
    except Exception as exc:
        logger.exception("generate_macro_outline failed: %s", exc)
        ctx = _OUTLINE_GENERATION_CTX.get() or {}
        _emit_outline_stage_error(
            emit,
            work_id=str(ctx.get("work_id") or ""),
            title="未命名作品",
            stage="macro",
            message=f"大纲生成失败：{exc}",
        )
        return _atomic_result(
            status="error",
            tool="generate_macro_outline",
            op_id="",
            message=f"大纲生成失败：{exc}",
        )
    finally:
        _OUTLINE_GENERATION_CTX.reset(token)


async def _generate_meso_outline_coroutine(
    idea: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """生成中纲（Meso Outline）：内部调用 LLM，通过 submit_meso_outline 入库。"""
    from app.models.work_model import Work
    from app.services.work_service import (
        _OUTLINE_GENERATION_CTX,
        SUBMIT_MESO_OUTLINE_TOOL,
    )

    db = _get_db(config)
    emit = _get_emit(config)
    try:
        work_id = work_id or _get_work_id(config)
    except ValueError:
        return _atomic_result(
            status="error",
            tool="generate_meso_outline",
            op_id="",
            message="无法获取作品ID，请先生成大纲（Macro Outline）以创建作品。",
        )
    user_id = config.get("configurable", {}).get("user_id")

    if not user_id:
        return _atomic_result(
            status="error",
            tool="generate_meso_outline",
            op_id="",
            message="未认证用户，无法生成中纲。",
        )

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(
            status="error",
            tool="generate_meso_outline",
            op_id="",
            message=f"作品 {work_id} 不存在。",
        )

    outline = work.outline_tree or {}
    macro_outline = outline.get("outline", {})
    macro_phases = macro_outline.get("macro_phases", [])
    if not macro_phases:
        return _atomic_result(
            status="error",
            tool="generate_meso_outline",
            op_id="",
            message="请先生成大纲（Macro Outline）。",
        )

    emit("stage_start", {"stage": "meso_outline_create", "label": "生成中纲"})

    token = _OUTLINE_GENERATION_CTX.set({
        "db": db,
        "user_id": user_id,
        "work_id": work_id,
        "idea": idea or work.idea or "",
        "tags_list": work.tags if hasattr(work, "tags") else [],
    })
    try:
        macro_phases_text = json.dumps(macro_phases, ensure_ascii=False, indent=2)
        core_chars = macro_outline.get("core_characters", [])
        core_chars_text = json.dumps(core_chars, ensure_ascii=False, indent=2)
        story = outline.get("story", {})
        title = story.get("title", work.title)

        prompt = (
            "你是网络小说策划编辑。请基于已有的大纲，撰写当前阶段的中纲文档。\n"
            f"作品标题：{title}\n"
            f"类型：{story.get('genre', '未分类')}\n\n"
            "已有宏观阶段：\n"
            f"{macro_phases_text}\n\n"
            "核心角色：\n"
            f"{core_chars_text}\n\n"
            "请撰写一份中纲文档（自然语言），内容应包括：\n"
            "1. 当前所处的宏观阶段及其核心目标\n"
            "2. 该阶段内各中纲节拍的剧情走向\n"
            "3. 角色安排和人物关系发展\n"
            "4. 情感脉络和张力设计\n"
            "5. 关键冲突和转折点\n"
            "文档应信息密集、条理清晰，便于章节作者快速理解当前创作方向。\n"
            "必须调用 submit_meso_outline，将中纲文档内容作为 meso_doc 参数传入。"
        )

        args = await _invoke_and_persist(
            prompt=prompt,
            submit_tool=SUBMIT_MESO_OUTLINE_TOOL,
            tool_name="submit_meso_outline",
            field_name="meso_doc",
            emit_fn=emit,
        )

        doc_text = args if isinstance(args, str) else str(args)
        _emit_outline_done(emit, work_id=work_id, title=work.title, stage="meso")

        return _atomic_result(
            status="applied",
            tool="generate_meso_outline",
            op_id="",
            message=f"中纲文档生成成功。作品「{work.title}」，文档长度 {len(doc_text)} 字。",
            diff={"work_id": work_id},
        )
    except Exception as exc:
        logger.exception("generate_meso_outline failed: %s", exc)
        _emit_outline_stage_error(
            emit,
            work_id=work_id,
            title=work.title,
            stage="meso",
            message=f"中纲生成失败：{exc}",
        )
        return _atomic_result(
            status="error",
            tool="generate_meso_outline",
            op_id="",
            message=f"中纲生成失败：{exc}",
        )
    finally:
        _OUTLINE_GENERATION_CTX.reset(token)


async def _generate_micro_outline_coroutine(
    idea: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """生成小纲（Micro Outline）：内部调用 LLM，通过 submit_micro_outline 入库。"""
    from app.models.work_model import Work
    from app.services.work_service import (
        _OUTLINE_GENERATION_CTX,
        SUBMIT_MICRO_OUTLINE_TOOL,
    )

    db = _get_db(config)
    emit = _get_emit(config)
    try:
        work_id = work_id or _get_work_id(config)
    except ValueError:
        return _atomic_result(
            status="error",
            tool="generate_micro_outline",
            op_id="",
            message="无法获取作品ID，请先生成大纲（Macro Outline）以创建作品。",
        )
    user_id = config.get("configurable", {}).get("user_id")

    if not user_id:
        return _atomic_result(
            status="error",
            tool="generate_micro_outline",
            op_id="",
            message="未认证用户，无法生成小纲。",
        )

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(
            status="error",
            tool="generate_micro_outline",
            op_id="",
            message=f"作品 {work_id} 不存在。",
        )

    outline = work.outline_tree or {}
    macro_outline = outline.get("outline", {})
    macro_phases = macro_outline.get("macro_phases", [])

    if not macro_phases:
        return _atomic_result(
            status="error",
            tool="generate_micro_outline",
            op_id="",
            message="请先生成大纲（Macro Outline）。",
        )

    emit("stage_start", {"stage": "micro_outline_create", "label": "生成小纲"})

    token = _OUTLINE_GENERATION_CTX.set({
        "db": db,
        "user_id": user_id,
        "work_id": work_id,
        "idea": idea or work.idea or "",
        "tags_list": work.tags if hasattr(work, "tags") else [],
    })
    try:
        macro_phases_text = json.dumps(macro_phases, ensure_ascii=False, indent=2)
        core_chars_text = json.dumps(macro_outline.get("core_characters", []), ensure_ascii=False, indent=2)
        story = outline.get("story", {})
        title = story.get("title", work.title)

        prompt = (
            "你是网络小说策划编辑。请基于已有的大纲和中纲，撰写小纲文档。\n"
            f"作品标题：{title}\n"
            f"类型：{story.get('genre', '未分类')}\n\n"
            "已有宏观阶段：\n"
            f"{macro_phases_text}\n\n"
            "核心角色：\n"
            f"{core_chars_text}\n\n"
            "请撰写一份小纲文档（自然语言），内容应包括：\n"
            "1. 接下来几章（3-5章）的场景安排\n"
            "2. 每个场景的出场人物、地点、冲突\n"
            "3. 情感节奏和张力递进设计\n"
            "4. 需要铺设的伏笔或回收的伏笔\n"
            "5. 与中纲方向的衔接点\n"
            "文档应信息密集、条理清晰，便于章节作者直接参考执行。\n"
            "必须调用 submit_micro_outline，将小纲文档内容作为 micro_doc 参数传入。"
        )

        args = await _invoke_and_persist(
            prompt=prompt,
            submit_tool=SUBMIT_MICRO_OUTLINE_TOOL,
            tool_name="submit_micro_outline",
            field_name="micro_doc",
            emit_fn=emit,
        )

        doc_text = args if isinstance(args, str) else str(args)
        _emit_outline_done(emit, work_id=work_id, title=work.title, stage="micro")

        return _atomic_result(
            status="applied",
            tool="generate_micro_outline",
            op_id="",
            message=f"小纲文档生成成功。作品「{work.title}」，文档长度 {len(doc_text)} 字。",
            diff={"work_id": work_id},
        )
    except Exception as exc:
        logger.exception("generate_micro_outline failed: %s", exc)
        _emit_outline_stage_error(
            emit,
            work_id=work_id,
            title=work.title,
            stage="micro",
            message=f"小纲生成失败：{exc}",
        )
        return _atomic_result(
            status="error",
            tool="generate_micro_outline",
            op_id="",
            message=f"小纲生成失败：{exc}",
        )
    finally:
        _OUTLINE_GENERATION_CTX.reset(token)


async def _generate_character_details_coroutine(
    idea: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """生成角色详情：基于 core_characters 简要信息生成完整角色卡。"""
    from app.models.work_model import Work
    from app.services.work_service import (
        _OUTLINE_GENERATION_CTX,
        SUBMIT_CHARACTER_DETAILS_TOOL,
    )

    db = _get_db(config)
    emit = _get_emit(config)
    try:
        work_id = work_id or _get_work_id(config)
    except ValueError:
        return _atomic_result(
            status="error",
            tool="generate_character_details",
            op_id="",
            message="无法获取作品ID，请先生成大纲（Macro Outline）以创建作品。",
        )
    user_id = config.get("configurable", {}).get("user_id")

    if not user_id:
        return _atomic_result(
            status="error",
            tool="generate_character_details",
            op_id="",
            message="未认证用户，无法生成角色详情。",
        )

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(
            status="error",
            tool="generate_character_details",
            op_id="",
            message=f"作品 {work_id} 不存在。",
        )

    outline = work.outline_tree or {}
    macro_outline = outline.get("outline", {})
    core_characters = macro_outline.get("core_characters", [])
    if not core_characters:
        return _atomic_result(
            status="error",
            tool="generate_character_details",
            op_id="",
            message="请先生成大纲（Macro Outline），其中需包含核心角色简介（core_characters）。",
        )

    emit("stage_start", {"stage": "character_details_create", "label": "生成角色详情"})

    # 将 core_characters 作为 briefs 供 submit 工具合并使用
    briefs = []
    for cc in core_characters:
        briefs.append({
            "name": cc.get("name", ""),
            "role_type": cc.get("role_type", "配角"),
            "gender": cc.get("gender", ""),
            "age": cc.get("age", ""),
            "first_appearance_stage": cc.get("first_appearance_stage", "M1"),
        })

    token = _OUTLINE_GENERATION_CTX.set({
        "db": db,
        "user_id": user_id,
        "work_id": work_id,
        "idea": idea or work.idea or "",
        "tags_list": work.tags if hasattr(work, "tags") else [],
        "briefs": briefs,
        "character_details": [],
    })
    try:
        core_chars_text = json.dumps(core_characters, ensure_ascii=False, indent=2)
        meso_stages = outline.get("meso", {}).get("meso_stages", [])
        meso_text = json.dumps(meso_stages, ensure_ascii=False, indent=2) if meso_stages else "（暂无中纲）"
        story = outline.get("story", {})
        title = story.get("title", work.title)

        prompt = (
            "你是网络小说角色设计专家。请基于已有的核心角色简介，为每个角色生成完整的角色卡。\n"
            f"作品标题：{title}\n"
            f"类型：{story.get('genre', '未分类')}\n\n"
            "核心角色简介（core_characters）：\n"
            f"{core_chars_text}\n\n"
            "中纲阶段（meso_stages，供参考角色在各阶段的行动）：\n"
            f"{meso_text}\n\n"
        )
        if idea:
            prompt += f"用户额外要求：{idea}\n\n"
        prompt += (
            "【任务】为上面每个角色生成详细角色卡（characters 数组）。\n"
            "每个角色包含：\n"
            "- name: 角色名（必须与 core_characters 中的 name 一致）\n"
            "- appearance: 外貌描写（50-100字）\n"
            "- personality: 性格特征（50-100字）\n"
            "- background: 背景来历（50-150字）\n"
            "- skills: 能力技能\n"
            "- current_status: 当前状态（如'存活'、'失踪'等）\n"
            "- current_goal: 当前目的/动机\n\n"
            "【JSON 约束】所有字符串值中禁止使用英文双引号，如需引用请使用中文双引号或单引号。\n"
            "必须调用 submit_character_details，不要输出普通文本。"
        )

        args = await _invoke_and_persist(
            prompt=prompt,
            submit_tool=SUBMIT_CHARACTER_DETAILS_TOOL,
            tool_name="submit_character_details",
            field_name="characters",
            emit_fn=emit,
        )

        char_count = len(args) if isinstance(args, list) else 0
        _emit_outline_done(
            emit, work_id=work_id, title=work.title, stage="character_details",
        )

        return _atomic_result(
            status="applied",
            tool="generate_character_details",
            op_id="",
            message=f"角色详情生成成功。作品「{work.title}」，共 {char_count} 个角色卡。",
            diff={"work_id": work_id, "character_count": char_count},
        )
    except Exception as exc:
        logger.exception("generate_character_details failed: %s", exc)
        _emit_outline_stage_error(
            emit,
            work_id=work_id,
            title=work.title,
            stage="character_details",
            message=f"角色详情生成失败：{exc}",
        )
        return _atomic_result(
            status="error",
            tool="generate_character_details",
            op_id="",
            message=f"角色详情生成失败：{exc}",
        )
    finally:
        _OUTLINE_GENERATION_CTX.reset(token)


generate_macro_outline = StructuredTool.from_function(
    func=None,
    coroutine=_generate_macro_outline_coroutine,
    name="generate_macro_outline",
    description="生成大纲（Macro Outline）并保存到数据库。包含 story、macro_phases、core_characters、ending。",
    args_schema=GenerateMacroOutlineInput,
)

generate_meso_outline = StructuredTool.from_function(
    func=None,
    coroutine=_generate_meso_outline_coroutine,
    name="generate_meso_outline",
    description="生成中纲（Meso Outline）并保存到数据库。需要先有大纲。包含 meso_stages。",
    args_schema=GenerateMesoOutlineInput,
)

generate_micro_outline = StructuredTool.from_function(
    func=None,
    coroutine=_generate_micro_outline_coroutine,
    name="generate_micro_outline",
    description="生成小纲（Micro Outline）并保存到数据库。需要先有大纲和中纲。包含 micro_scenes。",
    args_schema=GenerateMicroOutlineInput,
)

generate_character_details = StructuredTool.from_function(
    func=None,
    coroutine=_generate_character_details_coroutine,
    name="generate_character_details",
    description="基于大纲中的核心角色简介，生成完整角色卡（appearance/personality/background/skills等）。需要先有大纲。",
    args_schema=GenerateCharacterDetailsInput,
)


async def _edit_macro_outline_coroutine(
    suggestion: str,
    context_note: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """编辑大纲（Macro Outline）：读取当前 macro_outline，让 LLM 根据建议修改后重新入库。"""
    from app.models.work_model import Work
    from app.services.work_service import (
        _OUTLINE_GENERATION_CTX,
        SUBMIT_MACRO_OUTLINE_TOOL,
    )

    db = _get_db(config)
    emit = _get_emit(config)
    user_id = config.get("configurable", {}).get("user_id")

    try:
        work_id = work_id or _get_work_id(config)
    except ValueError:
        return _atomic_result(
            status="error",
            tool="edit_macro_outline",
            op_id="",
            message="无法获取作品ID。",
        )

    user_message = (suggestion or "").strip()
    note = (context_note or "").strip()
    if note:
        user_message = f"{user_message}\n\n补充上下文：\n{note}"
    if not user_message:
        return _atomic_result(
            status="error",
            tool="edit_macro_outline",
            op_id="",
            message="suggestion 不能为空。",
        )

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(
            status="error",
            tool="edit_macro_outline",
            op_id="",
            message=f"作品 {work_id} 不存在。",
        )

    outline = work.outline_tree or {}
    macro_outline = outline.get("outline", {})
    if not macro_outline.get("macro_phases"):
        return _atomic_result(
            status="error",
            tool="edit_macro_outline",
            op_id="",
            message="当前作品尚无宏观大纲，请先生成。",
        )

    emit("stage_start", {"stage": "macro_outline_edit", "label": "编辑大纲"})

    token = _OUTLINE_GENERATION_CTX.set({
        "db": db,
        "user_id": user_id or "",
        "work_id": work_id,
        "idea": work.idea or "",
        "tags_list": work.tags if hasattr(work, "tags") else [],
    })
    try:
        story = outline.get("story", {})
        current_text = json.dumps(macro_outline, ensure_ascii=False, indent=2)

        prompt = (
            "你是网络小说策划编辑。用户希望修改已有的大纲（Macro Outline）。\n"
            f"作品标题：{story.get('title', work.title)}\n\n"
            "当前大纲（macro_outline）：\n"
            f"{current_text}\n\n"
            f"用户修改建议：{user_message}\n\n"
            "【任务】根据用户建议，输出修改后的完整大纲。结构包含：\n"
            "- story: {title, genre, volume}\n"
            "- macro_phases: 宏观阶段数组（每个含 id/name/goal/core_setting/chapter_range）\n"
            "- core_characters: 核心角色简介数组（每个含 name/role_type/brief）\n"
            "- ending: 结局方向（可选）\n\n"
            "注意：未涉及修改的部分应保持原样，不要自行删减或扩写。\n"
            "【JSON 约束】所有字符串值中禁止使用英文双引号，如需引用请使用中文双引号或单引号。\n"
            "必须调用 submit_macro_outline，不要输出普通文本。"
        )

        args = await _invoke_and_persist(
            prompt=prompt,
            submit_tool=SUBMIT_MACRO_OUTLINE_TOOL,
            tool_name="submit_macro_outline",
            emit_fn=emit,
        )

        phase_count = len(args.get("macro_phases", []))
        return _atomic_result(
            status="applied",
            tool="edit_macro_outline",
            op_id="",
            message=f"大纲编辑成功。宏观阶段 {phase_count} 个。",
            diff={"work_id": work_id, "macro_phase_count": phase_count},
        )
    except Exception as exc:
        logger.exception("edit_macro_outline failed: %s", exc)
        return _atomic_result(
            status="error",
            tool="edit_macro_outline",
            op_id="",
            message=f"大纲编辑失败：{exc}",
        )
    finally:
        _OUTLINE_GENERATION_CTX.reset(token)


async def _edit_meso_outline_coroutine(
    suggestion: str,
    context_note: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """编辑中纲（Meso Outline）：读取当前 meso_stages，让 LLM 根据建议修改后重新入库。"""
    from app.models.work_model import Work
    from app.services.work_service import (
        _OUTLINE_GENERATION_CTX,
        SUBMIT_MESO_OUTLINE_TOOL,
    )

    db = _get_db(config)
    emit = _get_emit(config)
    user_id = config.get("configurable", {}).get("user_id")

    try:
        work_id = work_id or _get_work_id(config)
    except ValueError:
        return _atomic_result(
            status="error",
            tool="edit_meso_outline",
            op_id="",
            message="无法获取作品ID。",
        )

    user_message = (suggestion or "").strip()
    note = (context_note or "").strip()
    if note:
        user_message = f"{user_message}\n\n补充上下文：\n{note}"
    if not user_message:
        return _atomic_result(
            status="error",
            tool="edit_meso_outline",
            op_id="",
            message="suggestion 不能为空。",
        )

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(
            status="error",
            tool="edit_meso_outline",
            op_id="",
            message=f"作品 {work_id} 不存在。",
        )

    outline = work.outline_tree or {}
    meso_stages = outline.get("meso", {}).get("meso_stages", [])
    macro_outline = outline.get("outline", {})
    if not meso_stages:
        return _atomic_result(
            status="error",
            tool="edit_meso_outline",
            op_id="",
            message="当前作品尚无中纲，请先生成。",
        )

    emit("stage_start", {"stage": "meso_outline_edit", "label": "编辑中纲"})

    token = _OUTLINE_GENERATION_CTX.set({
        "db": db,
        "user_id": user_id or "",
        "work_id": work_id,
        "idea": work.idea or "",
        "tags_list": work.tags if hasattr(work, "tags") else [],
    })
    try:
        story = outline.get("story", {})
        macro_text = json.dumps(macro_outline.get("macro_phases", []), ensure_ascii=False, indent=2)
        current_text = json.dumps(meso_stages, ensure_ascii=False, indent=2)

        prompt = (
            "你是网络小说策划编辑。用户希望修改已有的中纲（Meso Outline）。\n"
            f"作品标题：{story.get('title', work.title)}\n\n"
            "宏观阶段（macro_phases，供参考）：\n"
            f"{macro_text}\n\n"
            "当前中纲（meso_stages）：\n"
            f"{current_text}\n\n"
            f"用户修改建议：{user_message}\n\n"
            "【任务】根据用户建议，输出修改后的完整中纲。结构包含：\n"
            "meso_stages 数组，每个元素含：\n"
            "- id, macro_phase_id, name, summary, chapter_range, key_events,\n"
            "  participating_characters, emotional_arc\n\n"
            "注意：未涉及修改的部分应保持原样，不要自行删减或扩写。\n"
            "【JSON 约束】所有字符串值中禁止使用英文双引号，如需引用请使用中文双引号或单引号。\n"
            "必须调用 submit_meso_outline，不要输出普通文本。"
        )

        args = await _invoke_and_persist(
            prompt=prompt,
            submit_tool=SUBMIT_MESO_OUTLINE_TOOL,
            tool_name="submit_meso_outline",
            field_name="meso_stages",
            emit_fn=emit,
        )

        stage_count = len(args) if isinstance(args, list) else 0
        return _atomic_result(
            status="applied",
            tool="edit_meso_outline",
            op_id="",
            message=f"中纲编辑成功。中纲阶段 {stage_count} 个。",
            diff={"work_id": work_id, "meso_stage_count": stage_count},
        )
    except Exception as exc:
        logger.exception("edit_meso_outline failed: %s", exc)
        return _atomic_result(
            status="error",
            tool="edit_meso_outline",
            op_id="",
            message=f"中纲编辑失败：{exc}",
        )
    finally:
        _OUTLINE_GENERATION_CTX.reset(token)


async def _edit_micro_outline_coroutine(
    suggestion: str,
    context_note: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """编辑小纲（Micro Outline）：读取当前 micro_scenes，让 LLM 根据建议修改后重新入库。"""
    from app.models.work_model import Work
    from app.services.work_service import (
        _OUTLINE_GENERATION_CTX,
        SUBMIT_MICRO_OUTLINE_TOOL,
    )

    db = _get_db(config)
    emit = _get_emit(config)
    user_id = config.get("configurable", {}).get("user_id")

    try:
        work_id = work_id or _get_work_id(config)
    except ValueError:
        return _atomic_result(
            status="error",
            tool="edit_micro_outline",
            op_id="",
            message="无法获取作品ID。",
        )

    user_message = (suggestion or "").strip()
    note = (context_note or "").strip()
    if note:
        user_message = f"{user_message}\n\n补充上下文：\n{note}"
    if not user_message:
        return _atomic_result(
            status="error",
            tool="edit_micro_outline",
            op_id="",
            message="suggestion 不能为空。",
        )

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(
            status="error",
            tool="edit_micro_outline",
            op_id="",
            message=f"作品 {work_id} 不存在。",
        )

    outline = work.outline_tree or {}
    micro_scenes = outline.get("micro", {}).get("micro_scenes", [])
    meso_stages = outline.get("meso", {}).get("meso_stages", [])
    if not micro_scenes:
        return _atomic_result(
            status="error",
            tool="edit_micro_outline",
            op_id="",
            message="当前作品尚无小纲，请先生成。",
        )

    emit("stage_start", {"stage": "micro_outline_edit", "label": "编辑小纲"})

    token = _OUTLINE_GENERATION_CTX.set({
        "db": db,
        "user_id": user_id or "",
        "work_id": work_id,
        "idea": work.idea or "",
        "tags_list": work.tags if hasattr(work, "tags") else [],
    })
    try:
        story = outline.get("story", {})
        meso_text = json.dumps(meso_stages, ensure_ascii=False, indent=2) if meso_stages else "（暂无）"
        current_text = json.dumps(micro_scenes, ensure_ascii=False, indent=2)

        prompt = (
            "你是网络小说策划编辑。用户希望修改已有的小纲（Micro Outline）。\n"
            f"作品标题：{story.get('title', work.title)}\n\n"
            "中纲阶段（meso_stages，供参考）：\n"
            f"{meso_text}\n\n"
            "当前小纲（micro_scenes）：\n"
            f"{current_text}\n\n"
            f"用户修改建议：{user_message}\n\n"
            "【任务】根据用户建议，输出修改后的完整小纲。结构包含：\n"
            "micro_scenes 数组，每个元素含：\n"
            "- id, meso_stage_id, name, chapter, location, characters,\n"
            "  conflict, outcome, emotion_tone, pov, key_dialogue_hint\n\n"
            "注意：未涉及修改的部分应保持原样，不要自行删减或扩写。\n"
            "【JSON 约束】所有字符串值中禁止使用英文双引号，如需引用请使用中文双引号或单引号。\n"
            "必须调用 submit_micro_outline，不要输出普通文本。"
        )

        args = await _invoke_and_persist(
            prompt=prompt,
            submit_tool=SUBMIT_MICRO_OUTLINE_TOOL,
            tool_name="submit_micro_outline",
            field_name="micro_scenes",
            emit_fn=emit,
        )

        scene_count = len(args) if isinstance(args, list) else 0
        return _atomic_result(
            status="applied",
            tool="edit_micro_outline",
            op_id="",
            message=f"小纲编辑成功。场景 {scene_count} 个。",
            diff={"work_id": work_id, "micro_scene_count": scene_count},
        )
    except Exception as exc:
        logger.exception("edit_micro_outline failed: %s", exc)
        return _atomic_result(
            status="error",
            tool="edit_micro_outline",
            op_id="",
            message=f"小纲编辑失败：{exc}",
        )
    finally:
        _OUTLINE_GENERATION_CTX.reset(token)


edit_macro_outline = StructuredTool.from_function(
    func=None,
    coroutine=_edit_macro_outline_coroutine,
    name="edit_macro_outline",
    description="编辑大纲（Macro Outline）：传入修改建议，工具内部会读取并修改大纲。",
    args_schema=EditMacroOutlineInput,
)

edit_meso_outline = StructuredTool.from_function(
    func=None,
    coroutine=_edit_meso_outline_coroutine,
    name="edit_meso_outline",
    description="编辑中纲（Meso Outline）：传入修改建议，工具内部会读取并修改中纲。",
    args_schema=EditMesoOutlineInput,
)

edit_micro_outline = StructuredTool.from_function(
    func=None,
    coroutine=_edit_micro_outline_coroutine,
    name="edit_micro_outline",
    description="编辑小纲（Micro Outline）：传入修改建议，工具内部会读取并修改小纲。",
    args_schema=EditMicroOutlineInput,
)


async def _edit_character_details_coroutine(
    suggestion: str,
    character_name: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """编辑角色详情：读取当前角色卡，让 LLM 根据建议修改后重新入库。"""
    from app.models.work_model import Work
    from app.services.work_service import (
        _OUTLINE_GENERATION_CTX,
        SUBMIT_CHARACTER_DETAILS_TOOL,
    )

    db = _get_db(config)
    emit = _get_emit(config)
    user_id = config.get("configurable", {}).get("user_id")

    try:
        work_id = work_id or _get_work_id(config)
    except ValueError:
        return _atomic_result(
            status="error",
            tool="edit_character_details",
            op_id="",
            message="无法获取作品ID。",
        )

    suggestion_text = (suggestion or "").strip()
    if not suggestion_text:
        return _atomic_result(
            status="error",
            tool="edit_character_details",
            op_id="",
            message="suggestion 不能为空。",
        )

    with _with_lock(config):
        work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return _atomic_result(
            status="error",
            tool="edit_character_details",
            op_id="",
            message=f"作品 {work_id} 不存在。",
        )

    outline = work.outline_tree or {}
    characters = outline.get("characters", [])
    if not characters:
        return _atomic_result(
            status="error",
            tool="edit_character_details",
            op_id="",
            message="当前作品尚无角色卡，请先生成角色详情。",
        )

    # 如果指定了角色名，过滤出目标角色
    target_name = (character_name or "").strip()
    if target_name:
        target_chars = [c for c in characters if c.get("name") == target_name]
        if not target_chars:
            return _atomic_result(
                status="error",
                tool="edit_character_details",
                op_id="",
                message=f"未找到角色「{target_name}」，当前角色列表：{', '.join(c.get('name', '') for c in characters)}",
            )
    else:
        target_chars = characters

    emit("stage_start", {"stage": "character_details_edit", "label": "编辑角色详情"})

    # 构建 briefs 供 submit 工具使用
    briefs = []
    for c in characters:
        briefs.append({
            "name": c.get("name", ""),
            "role_type": c.get("role_type", "配角"),
            "gender": c.get("gender", ""),
            "age": c.get("age", ""),
            "first_appearance_stage": c.get("first_appearance_stage", "M1"),
        })

    # 已有详情供 LLM 参考
    existing_details = []
    for c in characters:
        existing_details.append({
            "name": c.get("name", ""),
            "appearance": c.get("appearance", ""),
            "personality": c.get("personality", ""),
            "background": c.get("background", ""),
            "skills": c.get("skills", ""),
            "current_status": c.get("current_status", "存活"),
            "current_goal": c.get("current_goal", ""),
            "first_appearance_stage": c.get("first_appearance_stage", "M1"),
        })

    token = _OUTLINE_GENERATION_CTX.set({
        "db": db,
        "user_id": user_id or "",
        "work_id": work_id,
        "idea": work.idea or "",
        "tags_list": work.tags if hasattr(work, "tags") else [],
        "briefs": briefs,
        "character_details": [],
    })
    try:
        story = outline.get("story", {})
        current_text = json.dumps(existing_details, ensure_ascii=False, indent=2)
        target_label = f"角色「{target_name}」" if target_name else "所有角色"

        prompt = (
            "你是网络小说角色设计专家。用户希望修改已有的角色卡。\n"
            f"作品标题：{story.get('title', work.title)}\n\n"
            f"当前角色卡：\n{current_text}\n\n"
            f"用户修改建议（针对{target_label}）：{suggestion_text}\n\n"
            "【任务】根据用户建议，输出修改后的角色卡。\n"
        )
        if target_name:
            prompt += f"只修改角色「{target_name}」，其他角色保持原样输出。\n"
        else:
            prompt += "输出所有角色的完整信息。\n"
        prompt += (
            "每个角色包含：\n"
            "- name: 角色名（保持不变）\n"
            "- appearance: 外貌描写\n"
            "- personality: 性格特征\n"
            "- background: 背景来历\n"
            "- skills: 能力技能\n"
            "- current_status: 当前状态\n"
            "- current_goal: 当前目的/动机\n"
            "- first_appearance_stage: 首次出场阶段（中纲阶段ID，如 M1、M6，对应大纲中 meso_stages 的 id）\n\n"
            "注意：未涉及修改的字段应保持原样。\n"
            "【JSON 约束】所有字符串值中禁止使用英文双引号，如需引用请使用中文双引号或单引号。\n"
            "必须调用 submit_character_details，不要输出普通文本。"
        )

        args = await _invoke_and_persist(
            prompt=prompt,
            submit_tool=SUBMIT_CHARACTER_DETAILS_TOOL,
            tool_name="submit_character_details",
            field_name="characters",
            emit_fn=emit,
        )

        char_count = len(args) if isinstance(args, list) else 0
        return _atomic_result(
            status="applied",
            tool="edit_character_details",
            op_id="",
            message=f"角色详情编辑成功。{target_label}，共 {char_count} 个角色卡。",
            diff={"work_id": work_id, "character_count": char_count},
        )
    except Exception as exc:
        logger.exception("edit_character_details failed: %s", exc)
        return _atomic_result(
            status="error",
            tool="edit_character_details",
            op_id="",
            message=f"角色详情编辑失败：{exc}",
        )
    finally:
        _OUTLINE_GENERATION_CTX.reset(token)


edit_character_details = StructuredTool.from_function(
    func=None,
    coroutine=_edit_character_details_coroutine,
    name="edit_character_details",
    description="编辑角色详情：传入修改建议和可选的角色名，工具内部会读取并修改角色卡。",
    args_schema=EditCharacterDetailsInput,
)


@tool(args_schema=ReplaceOutlineFieldInput)
def replace_outline_field(
    path: str,
    old_value: str,
    new_value: str,
    op_id: str,
    reason: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """原子替换大纲字段。仅修改一个字段，必须提供 path 与旧值校验。"""
    from app.models.work_model import Work

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
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
    updates: list[ReplaceOutlineFieldItem],
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """批量替换多个大纲字段。单次调用可提交多条 path/old/new。"""
    from app.models.work_model import Work
    import json

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
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
    path: str,
    mode: str,
    anchor_id: str,
    index: int,
    item: dict,
    op_id: str,
    reason: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """原子插入大纲节点。支持 append / after_id / before_id / index。"""
    from app.models.work_model import Work

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
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
    path: str,
    match_field: str,
    match_value: str,
    op_id: str,
    reason: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """原子删除大纲节点。按 match_field + match_value 匹配单条记录。"""
    from app.models.work_model import Work

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
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
    character_name: str,
    field: str,
    old_value: str,
    new_value: str,
    op_id: str,
    reason: str,
    config: RunnableConfig,
    work_id: str | None = None,
) -> str:
    """原子替换角色字段。只修改一个角色的一个字段。"""
    from app.models.work_model import Character

    db = _get_db(config)
    work_id = work_id or _get_work_id(config)
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
    first_appearance_stage: str,
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
        first_appearance_stage=first_appearance_stage,
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
def commit_or_rollback(action: str, config: RunnableConfig, work_id: str | None = None) -> str:
    """确认提交或回滚大纲变更。action 只能是 commit 或 rollback。"""
    db = _get_db(config)
    emit = _get_emit(config)
    work_id = work_id or _get_work_id(config)

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
        "first_appearance_stage": c.first_appearance_stage or "M1",
    }


_GENERATE_OUTLINE_DESCRIPTION = (
    "从零创建完整大纲并保存到数据库（一次调用完成，勿分步用自然语言代劳）。"
    "工具内部会依次生成并入库："
    "（1）作品 story（标题、类型、卷名）；"
    "（2）主线 timeline 节点；"
    "（3）角色卡 characters（含 name、role_type、gender、age、外貌、性格、背景、技能、当前状态、目标、首次出场章）；"
    "（4）支线 branches；"
    "（5）伏笔 foreshadowing；"
    "（6）角色-剧情关联 character_links。"
    "用户对节点数、角色数、伏笔数等数量约束必须完整写入 idea 参数。"
    "创建角色、支线、伏笔、主线时禁止在回复中用自然语言输出角色卡或大纲 JSON，必须调用本工具。"
)

generate_outline = StructuredTool.from_function(
    func=None,
    coroutine=_generate_outline_coroutine,
    name="generate_outline",
    description=_GENERATE_OUTLINE_DESCRIPTION,
    args_schema=GenerateOutlineInput,
)

# DEPRECATED: 未来删除，由 edit_macro/meso/micro_outline + edit_character_details 替代
edit_outline_by_suggestion = StructuredTool.from_function(
    func=None,
    coroutine=_edit_outline_by_suggestion_coroutine,
    name="edit_outline_by_suggestion",
    description="[已废弃] 单次调用完成大纲编辑。请使用 edit_macro_outline / edit_meso_outline / edit_micro_outline / edit_character_details 替代。",
    args_schema=EditOutlineBySuggestionInput,
)

# ── 导出工具列表 ──

CHILD_TODO_TOOLS = [
    create_child_todolist,
    read_child_todolist,
    update_child_task_status,
]

_OUTLINE_CORE_TOOLS = [
    read_outline,
    read_macro_outline,
    read_meso_outline,
    read_micro_outline,
    query_outline_characters,
    query_outline_related_chapters,
    # generate_outline 已移除，由 generate_macro/meso/micro_outline + generate_character_details 替代
    generate_macro_outline,
    generate_meso_outline,
    generate_micro_outline,
    generate_character_details,
    edit_outline_by_suggestion,  # DEPRECATED
    edit_macro_outline,
    edit_meso_outline,
    edit_micro_outline,
    edit_character_details,
]


def build_outline_tools(*, auto_mode: bool = True, enable_child_todolist: bool = True) -> list:
    """根据 auto_mode / enable_child_todolist 构建大纲工具集。"""
    from app.services.supervisor.tool_registry import build_outline_tools as _build

    return _build(auto_mode=auto_mode, enable_child_todolist=enable_child_todolist)


# 向后兼容：延迟初始化，避免循环导入
_OUTLINE_TOOLS_CACHE = None

def get_outline_tools(*, auto_mode: bool = True) -> list:
    """获取大纲工具集（延迟初始化）"""
    global _OUTLINE_TOOLS_CACHE
    if _OUTLINE_TOOLS_CACHE is None:
        _OUTLINE_TOOLS_CACHE = build_outline_tools(auto_mode=auto_mode)
    return _OUTLINE_TOOLS_CACHE

# 向后兼容
OUTLINE_TOOLS = None  # 将在首次访问时通过 get_outline_tools() 初始化
