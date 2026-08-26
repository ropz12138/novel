"""Registered chapter evaluation and word-count tools."""
import json
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from models.chapter import Chapter
from models.node import Node


def _get_db():
    from database import SessionLocal

    return SessionLocal()


def _get_current_work_id():
    try:
        from services.agents.supervisor import get_context

        return get_context().get("work_id")
    except Exception:
        return None


class EvaluateChapterInput(BaseModel):
    chapter_node_id: Optional[str] = Field(
        default=None,
        description="要评估的章节节点ID；省略则评估作品中按顺序最新且有正文的章节",
    )
    work_id: Optional[str] = Field(default=None, description="作品ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


def _parse_evaluate_chapter_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines if not line.strip().startswith("```")
        ).strip()
    data = json.loads(text)
    if "evaluation" not in data or "chapter_overview" not in data:
        raise ValueError("模型返回缺少 evaluation 或 chapter_overview")
    return data


def _upsert_chapter_summary(db, node: Node, overview: str) -> None:
    chapter = db.query(Chapter).filter(Chapter.node_id == node.id).first()
    if not chapter:
        chapter = Chapter(
            work_id=node.work_id,
            node_id=node.id,
            title=node.title or "",
            content=node.content or "",
        )
        db.add(chapter)
    chapter.summary = overview


async def _evaluate_chapter_coroutine(
    chapter_node_id=None,
    reason=None,
    work_id=None,
) -> str:
    from services.agents.llm import get_llm
    from services.chapter_history_service import (
        build_evaluate_chapter_messages,
        resolve_chapter_for_evaluation,
    )

    db = _get_db()
    try:
        effective_work_id = work_id or _get_current_work_id()
        if not effective_work_id:
            return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)

        chapter = resolve_chapter_for_evaluation(
            db, effective_work_id, chapter_node_id
        )
        if not chapter.content:
            return json.dumps({"error": "章节正文为空，无法评估"}, ensure_ascii=False)

        messages = build_evaluate_chapter_messages(db, effective_work_id, chapter)
        llm = get_llm(temperature=0.5, streaming=False)
        response = await llm.ainvoke(messages)
        content = getattr(response, "content", str(response))
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        parsed = _parse_evaluate_chapter_response(content)
        _upsert_chapter_summary(db, chapter, parsed["chapter_overview"])
        db.commit()

        return json.dumps(
            {
                "success": True,
                "chapter": {"id": chapter.id, "title": chapter.title},
                "evaluation": parsed["evaluation"],
                "chapter_overview": parsed["chapter_overview"],
            },
            ensure_ascii=False,
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except json.JSONDecodeError:
        return json.dumps({"error": "模型返回不是合法 JSON"}, ensure_ascii=False)
    except Exception as exc:
        db.rollback()
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


class CountChapterWordsInput(BaseModel):
    chapter_node_id: Optional[str] = Field(
        default=None,
        description="章节节点ID；省略则统计作品中按顺序最新且有正文的章节",
    )
    expected_word_count: Optional[int] = Field(
        default=None,
        description="期望字数；传入后会根据与实际字数的差异给出篇幅建议",
    )
    work_id: Optional[str] = Field(default=None, description="作品ID")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


async def _count_chapter_words_coroutine(
    chapter_node_id=None,
    expected_word_count=None,
    reason=None,
    work_id=None,
) -> str:
    from services.chapter_history_service import resolve_chapter_for_evaluation
    from services.chapter_word_count import (
        build_word_count_advice,
        chapter_body_word_count,
    )

    db = _get_db()
    try:
        effective_work_id = work_id or _get_current_work_id()
        if not effective_work_id:
            return json.dumps({"error": "未指定作品ID"}, ensure_ascii=False)
        if expected_word_count is not None and expected_word_count <= 0:
            return json.dumps({"error": "期望字数必须大于 0"}, ensure_ascii=False)

        chapter = resolve_chapter_for_evaluation(
            db, effective_work_id, chapter_node_id
        )
        word_count = chapter_body_word_count(chapter.content or "")
        payload = {
            "success": True,
            "chapter": {"id": chapter.id, "title": chapter.title},
            "word_count": word_count,
        }
        if expected_word_count is not None:
            payload["expected_word_count"] = expected_word_count
            payload["advice"] = build_word_count_advice(
                word_count, expected_word_count
            )
        return json.dumps(payload, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
    finally:
        db.close()


evaluate_chapter = StructuredTool.from_function(
    coroutine=_evaluate_chapter_coroutine,
    name="evaluate_chapter",
    description=(
        "以读者身份评估章节。system 注入角色设定；第一条 user 为前序章节"
        "（最近5章全文，更早章节用已存档概览）；第二条 user 为待评估章节全文。"
        "返回 evaluation（评估结果）与 chapter_overview（本章简短摘要，并写入章节摘要）。"
        "chapter_node_id 可省略，省略时评估最新有正文的章节。"
    ),
    args_schema=EvaluateChapterInput,
)

count_chapter_words = StructuredTool.from_function(
    coroutine=_count_chapter_words_coroutine,
    name="count_chapter_words",
    description=(
        "统计章节正文纯文字数（去除空格和换行）。"
        "可选 expected_word_count 对比期望字数并返回篇幅建议。"
        "chapter_node_id 可省略，省略时统计最新有正文的章节。"
    ),
    args_schema=CountChapterWordsInput,
)

chapter_tools = [evaluate_chapter, count_chapter_words]
