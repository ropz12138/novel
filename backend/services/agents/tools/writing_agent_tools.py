"""Supervisor → Writer 的结构化交接、独立执行及版本校验保存。"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from models.node import Node
from services.agents.subagent_runtime import invoke_isolated_subagent
from services.agents.tools.node_tools import ContentReplacement, _apply_content_replacements
from services.agents.tools.workflow_skill_tools import REFERENCE_ROOT

logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "writer_system.txt"
OPERATION_REFERENCES = {
    "write": ("chapter_writer.txt",),
    "rewrite": ("chapter_rewrite.txt",),
    "revise": ("chapter_local_edit.txt",),
    "humanize": ("fiction_humanizer.txt", "humanizer_agent.txt"),
}


class KnownInformation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character: str = Field(min_length=1, description="当前场景中的人物")
    known_information: str = Field(min_length=1, description="此刻已知信息，区分亲见、听闻与推测")
    source: str = Field(min_length=1, description="信息获得途径和正文依据；本章新信息注明获得场景")


class WritingBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_plan: str = Field(min_length=1, description="完整当前版本计划：章节期待与回报、有效阻力、人物目的、场景事件因果及结束状态；故事事实与预期阅读效果分别表达，具体文学表达由 Writer 完成")
    narrative_pov: str = Field(min_length=1, description="叙述视角、视角人物及信息范围")
    character_knowledge: list[KnownInformation] = Field(min_length=1, description="人物认知及来源，与世界事实分别交接")
    story_facts: str = Field(min_length=1, description="当前有效的故事事实与连续性数据")
    prose_requirements: str = Field(min_length=1, description="完整有效的文风、篇幅、作者要求与程度约束")
    revision_scope: str = Field(min_length=1, description="本次写作或修改的范围和目标状态")


class WritingAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter_node_id: str
    operation: Literal["write", "rewrite", "revise", "humanize"]
    source_node_ids: list[str] = Field(description="选定的完整前章、角色、世界观节点 ID；按提供顺序加载正文")
    writing_note_node_ids: list[str] = Field(
        default_factory=list,
        description="写作手法相关的笔记节点 ID；按提供顺序完整加载笔记内容",
    )
    brief: WritingBrief
    reason: str | None = None


class FullDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, description="完整章节正文")


class LocalEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replacements: list[ContentReplacement] = Field(min_length=1, description="old 为连续且唯一的原文，new 为修改结果")


def _json(**data):
    return json.dumps(data, ensure_ascii=False)


def _load_writing_task(request: WritingAgentInput, work_id: str) -> dict:
    from database import SessionLocal

    with SessionLocal() as db:
        target = db.query(Node).filter_by(id=request.chapter_node_id, work_id=work_id, type="chapter").first()
        if target is None:
            raise ValueError("目标章节不属于当前作品")
        content = target.content or ""
        if request.operation == "write" and content:
            raise ValueError("已有正文请使用 revise、humanize 或明确整章重写的 rewrite")
        sources = []
        for node_id in dict.fromkeys(request.source_node_ids):
            node = db.query(Node).filter_by(id=node_id, work_id=work_id).first()
            if node is None or node.type not in {"chapter", "character", "worldbuilding"}:
                raise ValueError("写作来源需要属于当前作品的章节、角色或世界观；作者要求通过 brief 交接")
            sources.append({"node_id": node.id, "type": node.type, "title": node.title, "content": node.content or ""})
        writing_notes = []
        for node_id in dict.fromkeys(request.writing_note_node_ids):
            node = db.query(Node).filter_by(id=node_id, work_id=work_id, type="note").first()
            if node is None:
                raise ValueError("写作手法笔记需要属于当前作品且节点类型为笔记")
            writing_notes.append({"node_id": node.id, "title": node.title, "content": node.content or ""})
        return {"operation": request.operation, "brief": request.brief.model_dump(),
                "target": {"node_id": target.id, "title": target.title, "content": content},
                "sources": sources, "writing_notes": writing_notes}


def _writer_prompt(operation: str) -> str:
    # 参考规则按完整文件传递，保留所有文学标准；最终交接协议由 writer_system 明确。
    references = "\n\n".join(
        f"参考规则 {name}\n{(REFERENCE_ROOT / name).read_text(encoding='utf-8')}"
        for name in OPERATION_REFERENCES[operation]
    )
    return references + "\n\n" + PROMPT_PATH.read_text(encoding="utf-8")


async def _run_writing_agent(
    chapter_node_id,
    operation,
    source_node_ids,
    brief,
    writing_note_node_ids=None,
    reason=None,
):
    from services.agents.supervisor import get_context
    from services.agents.tools.node_tools import _update_node_async

    request = WritingAgentInput(chapter_node_id=chapter_node_id, operation=operation, source_node_ids=source_node_ids,
                                writing_note_node_ids=writing_note_node_ids or [], brief=brief, reason=reason)
    work_id = get_context().get("work_id")
    if not work_id:
        return _json(success=False, error="当前会话未绑定作品")
    try:
        task = _load_writing_task(request, work_id)
    except ValueError as exc:
        return _json(success=False, error=str(exc))
    baseline_content_sha256 = hashlib.sha256(task["target"]["content"].encode()).hexdigest()

    submitted: list[str] = []
    submitted_replacements: list[ContentReplacement] = []

    async def submit_writing(**kwargs):
        if submitted:
            raise ValueError("本次写作任务已经提交")
        if operation in {"write", "rewrite"}:
            content = FullDraft.model_validate(kwargs).content
            if not content.strip():
                raise ValueError("正文需要包含有效文本")
        else:
            edits = LocalEdits.model_validate(kwargs)
            content = _apply_content_replacements(task["target"]["content"], edits.replacements)
            submitted_replacements.extend(edits.replacements)
        submitted.append(content)
        return _json(success=True, submitted=True)

    submit = StructuredTool.from_function(
        coroutine=submit_writing, name="submit_writing", return_direct=True,
        args_schema=FullDraft if operation in {"write", "rewrite"} else LocalEdits,
        description="提交本次写作结果。完整写作提交 content；局部编辑提交精确 replacements。",
    )
    emit = get_context().get("emit")
    if emit:
        await emit("stage_start", {"stage": "writing", "label": "写作子 Agent 正在创作"})
    try:
        await invoke_isolated_subagent(name="writer", system_prompt=_writer_prompt(operation), task=task, tools=[submit])
    except Exception as exc:
        logger.exception("writer failed chapter=%s", chapter_node_id)
        return _json(success=False, agent="writer", error_code="writer_failed", error=str(exc),
                     operation=operation,
                     revision_scope=request.brief.revision_scope,
                     message="保留原操作与修改范围，依据具体失败原因继续原任务；扩大范围需要作者明确决定。")
    if len(submitted) != 1:
        return _json(success=False, agent="writer", error_code="missing_submission", error="写作子 Agent 未提交正文")
    result = json.loads(await _update_node_async(
        node_id=chapter_node_id,
        content=submitted[0] if operation in {"write", "rewrite"} else None,
        mode="overwrite" if operation in {"write", "rewrite"} else "replace",
        replacements=submitted_replacements or None, reason=reason,
        expected_content_sha256=baseline_content_sha256, expected_work_id=work_id,
    ))
    if not result.get("success"):
        return _json(**result)
    return _json(success=True, agent="writer", chapter_node_id=chapter_node_id,
                 content_sha256=hashlib.sha256(submitted[0].encode()).hexdigest(),
                 message="正文已保存，请回读最新正文并更新章节笔记。")


run_writing_agent = StructuredTool.from_function(
    coroutine=_run_writing_agent, name="run_writing_agent", args_schema=WritingAgentInput,
    description=("委派独立上下文的 Writer 子 Agent 创作并保存正文。write 写空章，rewrite 整章重写，"
                 "revise 局部修订，humanize 局部自然化。交接当前版本的事实、角色认知、场景目标和完整要求；"
                 "来源正文按节点完整读取，writing_note_node_ids 中的写作手法笔记单独完整加载；"
                 "历史聊天及其他笔记留在 Supervisor。成功后回读正文并维护笔记。"),
)
