import json
import re
from pathlib import Path

from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.work_model import Chapter, Work
from app.schemas.evaluation_schema import RoleEvaluation
from app.services.work_service import WorkService

PROMPT_DIR = Path(__file__).resolve().parent / "prompt_templates"


def _read_prompt(file_name: str) -> str:
    return (PROMPT_DIR / file_name).read_text(encoding="utf-8")


def _get_llm(temperature: float = 0.3) -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=temperature,
        streaming=False,
    )


def _extract_json_block(raw: str) -> dict | None:
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except Exception:
            return None

    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        try:
            return json.loads(json_match.group())
        except Exception:
            return None
    return None


def _normalize_result(payload: dict | None) -> RoleEvaluation:
    if not payload:
        return RoleEvaluation(
            total_score=0,
            scores={},
            strengths=[],
            issues=["评估结果解析失败"],
            suggestions=["请重试评估"],
        )

    scores = payload.get("scores", {}) if isinstance(payload.get("scores", {}), dict) else {}
    total = payload.get("total_score", 0)
    try:
        total = int(total)
    except Exception:
        total = 0

    return RoleEvaluation(
        total_score=max(0, min(60, total)),
        scores={str(k): int(v) for k, v in scores.items() if isinstance(v, (int, float, str)) and str(v).isdigit()},
        strengths=[str(i) for i in payload.get("strengths", []) if str(i).strip()],
        issues=[str(i) for i in payload.get("issues", []) if str(i).strip()],
        suggestions=[str(i) for i in payload.get("suggestions", []) if str(i).strip()],
    )


def _prepare_context(db: Session, work_id: str, chapter_number: int) -> tuple[Work, Chapter, str, str]:
    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        raise ValueError("作品不存在")

    chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
    if not chapter:
        raise ValueError("章节不存在")

    chapter_outline = WorkService._find_chapter_outline(work.outline_tree, chapter_number)

    prev_chapters = (
        db.query(Chapter)
        .filter_by(work_id=work_id)
        .filter(Chapter.chapter_number < chapter_number)
        .filter(Chapter.content != "")
        .order_by(Chapter.chapter_number.desc())
        .limit(3)
        .all()
    )
    prev_chapters.reverse()
    if prev_chapters:
        parts = []
        for ch in prev_chapters:
            summary = ch.content[:800] + ("..." if len(ch.content) > 800 else "")
            parts.append(f"--- 第{ch.chapter_number}章 {ch.title} ---\n{summary}")
        previous = "\n\n".join(parts)
    else:
        previous = "（这是第一章，暂无前文）"

    return work, chapter, chapter_outline, previous


class EvaluationAgent:
    async def evaluate_chapter(
        self,
        *,
        db: Session,
        work_id: str,
        chapter_number: int,
        chapter_content_override: str = "",
    ) -> tuple[str, RoleEvaluation, RoleEvaluation]:
        work, chapter, chapter_outline, previous_chapters = _prepare_context(db, work_id, chapter_number)
        chapter_content = chapter_content_override.strip() or (chapter.content or "")
        if not chapter_content:
            raise ValueError("章节正文为空，无法评估")

        story_info = json.dumps(work.outline_tree.get("story", {}), ensure_ascii=False)

        shared_inputs = {
            "story_info": story_info,
            "chapter_outline": chapter_outline or "（未找到本章大纲）",
            "chapter_title": chapter.title or f"第{chapter_number}章",
            "chapter_content": chapter_content,
            "previous_chapters": previous_chapters,
        }

        llm = _get_llm(temperature=0.2)

        editor_prompt = PromptTemplate.from_template(_read_prompt("agent_evaluate_editor.txt"))
        reader_prompt = PromptTemplate.from_template(_read_prompt("agent_evaluate_reader.txt"))

        editor_raw = await (editor_prompt | llm).ainvoke(shared_inputs)
        reader_raw = await (reader_prompt | llm).ainvoke(shared_inputs)

        editor_text = editor_raw.content if hasattr(editor_raw, "content") else str(editor_raw)
        reader_text = reader_raw.content if hasattr(reader_raw, "content") else str(reader_raw)

        editor = _normalize_result(_extract_json_block(editor_text))
        reader = _normalize_result(_extract_json_block(reader_text))
        title = chapter.title or f"第{chapter_number}章"
        return title, editor, reader
