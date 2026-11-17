"""Independent prose generation: no Supervisor history or tools reach Writer."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, model_validator

import database
from models.chapter import Chapter
from models.node import Node
from services.agent_paragraphs import content_sha256, split_paragraphs
from services.chapter_catalog_service import build_chapter_catalog
from services.agents import llm

PROMPT_PATH = Path(__file__).parent / "prompts" / "writer_system.txt"


class WriterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_node_id: str
    expected_content_sha256: str
    author_request: str = Field(pattern=r"\S", description="作者本轮原话，完整保留适用要求与修改范围")
    chapter_task: str = Field(pattern=r"\S", description="核心阅读体验、目标、必写事件、结果与创作边界；具体实现留给 Writer")
    story_overview: str = Field(default="", description="作品类型、核心看点、当前阶段与长线方向")
    story_memory: str = Field(default="", description="核对后的较早事实、资源与未决线索，仅交接本章有关内容")
    source_node_ids: list[str] = Field(default_factory=list, description="相关人物、设定、笔记及需回查的章节真实 ID；程序读取原文")
    writing_preferences: str = Field(default="", description="适用的文风、视角及长期创作要求")
    revision_instructions: str = Field(default="", description="采纳的评审建议、需保留的事实及修改目标；新写时留空")
    target_word_count: int = Field(default=2000, gt=0)
    mode: Literal["overwrite", "replace"] = "overwrite"
    start_paragraph: int | None = Field(default=None, ge=1)
    end_paragraph: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_range(self):
        if self.mode == "replace":
            if self.start_paragraph is None or self.end_paragraph is None or self.start_paragraph > self.end_paragraph:
                raise ValueError("局部修改需要有效的连续段落范围")
        elif self.start_paragraph is not None or self.end_paragraph is not None:
            raise ValueError("整章写作不接受段落范围")
        return self


class WriterContextError(ValueError):
    def __init__(self, message: str, code: str = "invalid_writer_context"):
        super().__init__(message)
        self.code = code


def _load_writer_context(work_id: str, request: WriterInput) -> str:
    """Fresh work-scoped source text, excluding engineering metadata and review notes."""
    with database.open_db() as db:
        chapters, _, _ = build_chapter_catalog(db, work_id)
        position = next((i for i, n in enumerate(chapters) if n.id == request.chapter_node_id), None)
        if position is None:
            raise WriterContextError("目标须为当前作品的章节")
        target = chapters[position]
        current = target.content or ""
        if content_sha256(current) != request.expected_content_sha256:
            raise WriterContextError("当前章节正文已变化，请重新读取后修改", "content_changed")

        selection = ""
        if request.mode == "replace":
            paragraphs = split_paragraphs(current)
            start, end = request.start_paragraph, request.end_paragraph
            if end > len(paragraphs):
                raise WriterContextError("局部修改范围超出当前正文")
            selection = current[paragraphs[start - 1].start:paragraphs[end - 1].end]

        source_ids = list(dict.fromkeys(request.source_node_ids))
        sources = {}
        if source_ids:
            sources = {n.id: n for n in db.query(Node).filter(
                Node.work_id == work_id, Node.id.in_(source_ids)
            ).all()}
            if len(sources) != len(source_ids):
                raise WriterContextError("参考节点不存在或不属于当前作品")
            if any(n.type == "reviewer_note" for n in sources.values()):
                raise WriterContextError("Reviewer 专用笔记不属于 Writer 上下文")

        recent = [n for n in chapters[:position] if (n.content or "").strip()][-3:]
        recent_ids = {n.id for n in recent}
        chapter_positions = {n.id: i for i, n in enumerate(chapters)}
        note_ids = recent_ids | {target.id} | {n.id for n in sources.values() if n.type == "chapter"}
        notes = {row.node_id: row.notes or "" for row in db.query(Chapter).filter(
            Chapter.work_id == work_id, Chapter.node_id.in_(note_ids)
        ).all()}

        sections = []

        def add(title, content):
            if content and content.strip():
                sections.append(f"## {title}\n{content}")

        add("作者原话与本轮要求", request.author_request)
        add("作品方向与当前阶段", request.story_overview)
        add("写作偏好", request.writing_preferences)
        for note in db.query(Node).filter(
            Node.work_id == work_id, Node.type == "note"
        ).order_by(Node.sort_order, Node.id).all():
            add(f"作品笔记：{note.title}（按适用范围使用）", note.content or "")

        for node_id in source_ids:
            node = sources[node_id]
            if node.id == target.id or node.id in recent_ids or node.type == "note":
                continue
            if node.type == "chapter":
                later = chapter_positions[node.id] > position
                label = "后续章节（用于修订兼容性核对，人物知识以当前时间为准）" if later else "相关较早章节"
                add(f"{label}：{node.title}", node.content or "")
                add(f"相关章节笔记：{node.title}（区分计划与事实）", notes.get(node.id, ""))
            else:
                add(f"相关设定：{node.title}", node.content or "")
                if node.type == "character":
                    storylines = (node.extra_data or {}).get("storylines")
                    if storylines:
                        add(f"人物发展线：{node.title}（区分规划与已发生事实）",
                            json.dumps(storylines, ensure_ascii=False))

        add("较早故事记忆与核对结论", request.story_memory)
        for node in recent:
            add(f"前文原文：{node.title}", node.content or "")
            add(f"前章笔记：{node.title}（正文优先于笔记中的计划）", notes.get(node.id, ""))
        add(f"目标章节：{target.title}", current)
        add("本章笔记（尚未成文的内容是计划）", notes.get(target.id, ""))
        add("本章任务：必写事件、阅读目标与边界", request.chapter_task)
        add("修订要求（仅采纳的意见）", request.revision_instructions)
        if request.mode == "replace":
            add("待替换的连续原文（输出此片段的完整改写）", selection)
            add("输出范围", "输出指定片段的完整改写，范围外原文由程序原样保留。以原片段及本次要求决定篇幅。")
        else:
            add("输出范围", f"输出完整章节正文，篇幅约 {request.target_word_count} 字；首段从故事内容开始，末段落在故事现场。")
        return "\n\n".join(sections)


async def generate_prose(brief: str) -> str:
    """A fresh, tool-free model request inheriting the user's model preference."""
    model = llm.get_deep_agent_model(temperature=0.7, **llm.context_model_pref_kwargs())
    response = await model.ainvoke(
        [SystemMessage(content=PROMPT_PATH.read_text(encoding="utf-8")), HumanMessage(content=brief)],
        config={"tags": ["novel:subagent"], "metadata": {"novel_agent_role": "writer"}},
    )
    content = response.content
    if getattr(response, "tool_calls", None) or not isinstance(content, str) or not content.strip():
        raise WriterContextError("Writer 未返回有效的纯正文", "writer_empty_output")
    return content.strip("\n")


async def _compose_chapter(**kwargs):
    from services.agents.supervisor import get_context, set_context, reset_context
    from services.agents.tools.supervisor_node_tools import _update

    # StructuredTool 已完成入口校验，内部按已验证的字段构造类型。
    request = WriterInput.model_construct(**kwargs)
    parent = get_context()
    work_id = parent.get("work_id")
    if not work_id:
        return json.dumps({"success": False, "error": "当前会话未绑定作品"}, ensure_ascii=False)
    try:
        brief = await asyncio.to_thread(_load_writer_context, work_id, request)
        token = set_context({**parent, "agent_role": "writer"})
        try:
            prose = await generate_prose(brief)
        finally:
            reset_context(token)
    except WriterContextError as exc:
        return json.dumps({"success": False, "error_code": exc.code, "error": str(exc)}, ensure_ascii=False)

    # Retain original content hash; never silently overwrite a concurrent author edit.
    save = {"node_id": request.chapter_node_id, "expected_content_sha256": request.expected_content_sha256,
            "mode": request.mode, "reason": "独立 Writer 正文创作"}
    if request.mode == "overwrite":
        save["content"] = prose
    else:
        save["replacements"] = [{"start_paragraph": request.start_paragraph,
                                  "end_paragraph": request.end_paragraph, "new": prose}]
    return await _update(**save)


compose_chapter = StructuredTool.from_function(
    coroutine=_compose_chapter, name="compose_chapter", args_schema=WriterInput,
    description=("使用独立无工具 Writer 创作或文学修订章节并通过现有版本校验保存。"
                 "完整交接作者要求、章节目标、相关真实节点 ID、较早事实和必要修订意见；"
                 "程序读取当前正文、最近三章原文和笔记。局部修改指定单个连续段落范围；"
                 "纯删除或已确定字词替换可直接 update_node。保存后 Supervisor 回读核对。"),
)
