"""确定性章节字数统计工具。"""
import json
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field



def _get_db():
    from database import SessionLocal

    return SessionLocal()


def _get_current_work_id():
    try:
        from services.agents.supervisor import get_context

        return get_context().get("work_id")
    except Exception:
        return None


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

chapter_tools = [count_chapter_words]
