"""Chapter metadata service.

Provides:
- write-time context pack assembly
- LLM metadata generation
- persistence into chapter_metadata
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from sqlalchemy.orm import Session

from app.models.work_model import Chapter, ChapterMetadata, Character, Work, _uuid
from app.services.supervisor.sub_agent_base import get_llm


class OutlineLink(BaseModel):
    type: str
    id: str
    relevance: str


class InvolvedCharacter(BaseModel):
    name: str
    actions: str
    status_change: str | None = None


class Foreshadow(BaseModel):
    type: str
    content: str
    plant_node: str | None = None
    payoff_node: str | None = None


class Fact(BaseModel):
    key: str
    value: str


class ChapterMetadataOutput(BaseModel):
    summary: str = ""
    key_plot_points: list[str] = Field(default_factory=list)
    outline_links: list[OutlineLink] = Field(default_factory=list)
    involved_characters: list[InvolvedCharacter] = Field(default_factory=list)
    foreshadows: list[Foreshadow] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)


class _SubmitChapterMetadataInput(ChapterMetadataOutput):
    """Tool-call payload for chapter metadata extraction."""


def _submit_chapter_metadata_tool(**kwargs) -> str:
    """Accept extracted chapter metadata as structured tool arguments."""
    return "chapter_metadata_received"


SUBMIT_CHAPTER_METADATA_TOOL = StructuredTool.from_function(
    func=_submit_chapter_metadata_tool,
    name="submit_chapter_metadata",
    description=(
        "提交章节元数据。必须严格提供 ChapterMetadataOutput 结构："
        "summary、key_plot_points、outline_links、involved_characters、foreshadows、facts。"
    ),
    args_schema=_SubmitChapterMetadataInput,
)


def _extract_tool_calls(ai_msg: Any) -> list[dict]:
    """Return tool calls exposed on AIMessage.tool_calls only."""
    return list(getattr(ai_msg, "tool_calls", None) or [])


def _message_text(ai_msg: Any) -> str:
    content = getattr(ai_msg, "content", "") or ""
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content)


def _parse_metadata_from_tool_call(ai_msg: Any) -> ChapterMetadataOutput:
    for call in _extract_tool_calls(ai_msg):
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        if name != "submit_chapter_metadata":
            continue
        args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
        if hasattr(args, "model_dump"):
            args = args.model_dump()
        if not isinstance(args, dict):
            raise ValueError("submit_chapter_metadata tool args must be an object")
        return ChapterMetadataOutput.model_validate(args)

    preview = _message_text(ai_msg)[:500]
    raise ValueError(
        "章节元数据生成失败：模型未调用 submit_chapter_metadata 工具。"
        f"模型输出预览：{preview}"
    )


class ChapterOutlineSyncService:
    """Backward-compatible name; now drives chapter_metadata."""

    @staticmethod
    def build_write_context(
        db: Session,
        *,
        work_id: str,
        chapter_number: int,
        user_instruction: str,
    ) -> str:
        work = db.query(Work).filter_by(id=work_id).first()
        chapters = (
            db.query(Chapter)
            .filter(Chapter.work_id == work_id, Chapter.chapter_number < chapter_number)
            .order_by(Chapter.chapter_number.asc())
            .all()
        )
        metadata_rows = (
            db.query(ChapterMetadata)
            .filter(ChapterMetadata.work_id == work_id, ChapterMetadata.chapter_number < chapter_number)
            .order_by(ChapterMetadata.chapter_number.asc())
            .all()
        )
        meta_map = {m.chapter_number: m for m in metadata_rows}

        summary_lines: list[str] = []
        for ch in chapters:
            meta_summary = (meta_map.get(ch.chapter_number).summary if meta_map.get(ch.chapter_number) else "") or ""
            summary = meta_summary.strip() or (ch.content or "").strip()[:120]
            summary_lines.append(f"- 第{ch.chapter_number}章：{summary}")

        fact_lines: list[str] = []
        recent_meta = (
            db.query(ChapterMetadata)
            .filter(ChapterMetadata.work_id == work_id, ChapterMetadata.chapter_number < chapter_number)
            .order_by(ChapterMetadata.chapter_number.desc())
            .limit(8)
            .all()
        )
        for m in recent_meta:
            for f in (m.facts or [])[:6]:
                if isinstance(f, dict):
                    key = str(f.get("key", "")).strip()
                    val = str(f.get("value", "")).strip()
                    if key or val:
                        fact_lines.append(f"- [第{m.chapter_number}章] {key}: {val}")

        referenced = set(int(x) for x in re.findall(r"第(\d+)章", user_instruction or ""))
        excerpt_lines: list[str] = []
        if referenced:
            selected = (
                db.query(Chapter)
                .filter(Chapter.work_id == work_id, Chapter.chapter_number.in_(sorted(referenced)))
                .order_by(Chapter.chapter_number.asc())
                .all()
            )
            for ch in selected:
                excerpt = (ch.content or "").strip()
                if len(excerpt) > 280:
                    excerpt = excerpt[:280] + "..."
                excerpt_lines.append(f"- 第{ch.chapter_number}章原文片段：{excerpt}")

        outline = (work.outline_tree or {}) if work else {}
        timeline = outline.get("timeline") if isinstance(outline, dict) else []
        timeline_lines = []
        for node in timeline or []:
            try:
                if int(node.get("chapter_start", 10**9)) <= chapter_number <= int(node.get("chapter_end", -1)):
                    timeline_lines.append(
                        f"- 节点{node.get('id', '')}：{node.get('development_node', '')}；摘要：{node.get('summary', '')}"
                    )
            except Exception:
                continue

        parts = [
            "【写作上下文包】",
            "1) 全前文梗概链：",
            "\n".join(summary_lines) if summary_lines else "- （无历史章节）",
            "2) 当前章关联大纲节点：",
            "\n".join(timeline_lines) if timeline_lines else "- （未命中范围节点）",
            "3) 近章设定事实：",
            "\n".join(fact_lines) if fact_lines else "- （暂无）",
        ]
        if excerpt_lines:
            parts.extend(["4) 按需查询的章节原文片段：", "\n".join(excerpt_lines)])
        parts.append("请保证与以上上下文一致，避免设定冲突和剧情跳跃。")
        return "\n".join(parts)

    @staticmethod
    async def generate_metadata(
        *,
        chapter_number: int,
        title: str,
        content: str,
        outline_tree: dict | None,
        characters: list[Character],
        previous_metadata: list[ChapterMetadata],
    ) -> ChapterMetadataOutput:
        llm = get_llm(temperature=0.2, streaming=False)
        llm_with_tools = llm.bind_tools(
            [SUBMIT_CHAPTER_METADATA_TOOL],
            tool_choice="submit_chapter_metadata",
            extra_body={"enable_thinking": False},
        )

        timeline = (outline_tree or {}).get("timeline", []) if isinstance(outline_tree, dict) else []
        branches = (outline_tree or {}).get("branches", []) if isinstance(outline_tree, dict) else []
        foreshadowing = (outline_tree or {}).get("foreshadowing", []) if isinstance(outline_tree, dict) else []

        characters_payload = [
            {
                "name": c.name,
                "role_type": c.role_type,
                "current_status": c.current_status,
                "current_goal": c.current_goal,
                "last_location": c.last_location,
                "last_chapter": c.last_chapter,
            }
            for c in characters
        ]

        prev_payload = [
            {
                "chapter_number": m.chapter_number,
                "summary": m.summary,
                "foreshadows": m.foreshadows,
            }
            for m in previous_metadata
        ]

        prompt = (
            "你是小说章节元数据抽取器。请根据正文和上下文抽取结构化元数据。"
            "必须且只调用 submit_chapter_metadata 工具，不要输出解释性文字。"
            "要求：summary 为100-200字中文摘要；key_plot_points 3-8条；"
            "outline_links 仅保留本章真实关联，且每项必须包含 type、id、relevance；"
            "involved_characters 仅列本章实际出场角色，且每项必须是对象，包含 name、actions，可选 status_change；"
            "foreshadows 包含 planted/paid_off/mentioned 等 type 和 content，可选 plant_node/payoff_node；"
            "facts 提取高价值设定事实，且每项必须是对象，包含 key、value。"
        )

        payload = {
            "chapter_number": chapter_number,
            "chapter_title": title,
            "chapter_content": content,
            "timeline": timeline,
            "branches": branches,
            "foreshadowing": foreshadowing,
            "characters": characters_payload,
            "previous_metadata": prev_payload,
        }

        human_content = (
            f"## 第{chapter_number}章「{title}」正文\n\n"
            f"{content}\n\n"
            f"## 大纲时间线\n{json.dumps(timeline, ensure_ascii=False, indent=2) if timeline else '（无）'}\n\n"
            f"## 大纲支线\n{json.dumps(branches, ensure_ascii=False, indent=2) if branches else '（无）'}\n\n"
            f"## 大纲伏笔设定\n{json.dumps(foreshadowing, ensure_ascii=False, indent=2) if foreshadowing else '（无）'}\n\n"
            f"## 角色状态\n{json.dumps(characters_payload, ensure_ascii=False, indent=2) if characters_payload else '（无）'}\n\n"
            f"## 前文元数据摘要\n{json.dumps(prev_payload, ensure_ascii=False, indent=2) if prev_payload else '（无）'}"
        )

        response = await llm_with_tools.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=human_content),
        ])
        return _parse_metadata_from_tool_call(response)

    @staticmethod
    def persist_metadata(
        db: Session,
        *,
        work_id: str,
        chapter_number: int,
        metadata: ChapterMetadataOutput,
    ) -> ChapterMetadata:
        row = (
            db.query(ChapterMetadata)
            .filter_by(work_id=work_id, chapter_number=chapter_number)
            .first()
        )
        if not row:
            row = ChapterMetadata(id=_uuid(), work_id=work_id, chapter_number=chapter_number)
            db.add(row)
            db.flush()

        row.summary = metadata.summary or ""
        row.key_plot_points = [str(x) for x in (metadata.key_plot_points or [])]
        row.outline_links = [x.model_dump() for x in (metadata.outline_links or [])]
        row.involved_characters = [x.model_dump() for x in (metadata.involved_characters or [])]
        row.foreshadows = [x.model_dump() for x in (metadata.foreshadows or [])]
        row.facts = [x.model_dump() for x in (metadata.facts or [])]
        return row

    @staticmethod
    async def generate_and_persist(
        db: Session,
        *,
        work: Work,
        chapter: Chapter,
    ) -> ChapterMetadata:
        chars = db.query(Character).filter_by(work_id=work.id).all()
        prev_meta = (
            db.query(ChapterMetadata)
            .filter(ChapterMetadata.work_id == work.id, ChapterMetadata.chapter_number < chapter.chapter_number)
            .order_by(ChapterMetadata.chapter_number.desc())
            .limit(12)
            .all()
        )
        generated = await ChapterOutlineSyncService.generate_metadata(
            chapter_number=chapter.chapter_number,
            title=chapter.title or f"第{chapter.chapter_number}章",
            content=chapter.content or "",
            outline_tree=work.outline_tree or {},
            characters=chars,
            previous_metadata=prev_meta,
        )
        row = ChapterOutlineSyncService.persist_metadata(
            db,
            work_id=work.id,
            chapter_number=chapter.chapter_number,
            metadata=generated,
        )
        return row


__all__ = [
    "ChapterOutlineSyncService",
    "ChapterMetadataOutput",
]
