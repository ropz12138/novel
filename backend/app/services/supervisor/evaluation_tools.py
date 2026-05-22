"""EvaluationAgent 工具集

章节评估子 Agent 可调用的工具，封装章节读取、上下文查询和双视角评估。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompt_templates"


# ── Tool input schemas ──


class ReadChapterForEvalInput(BaseModel):
    work_id: str = Field(description="作品ID")
    chapter_number: int = Field(description="章节号")


class ReadChapterOutlineForEvalInput(BaseModel):
    work_id: str = Field(description="作品ID")
    chapter_number: int = Field(description="章节号")


class ReadPreviousChaptersForEvalInput(BaseModel):
    work_id: str = Field(description="作品ID")
    chapter_number: int = Field(description="当前章节号")
    limit: int = Field(default=3, description="读取前几章")


class EvaluateAsEditorInput(BaseModel):
    chapter_content: str = Field(description="要评估的章节正文")
    story_info: str = Field(default="", description="作品信息")
    chapter_outline: str = Field(default="", description="本章大纲")
    previous_chapters: str = Field(default="", description="前文回顾")


class EvaluateAsReaderInput(BaseModel):
    chapter_content: str = Field(description="要评估的章节正文")
    story_info: str = Field(default="", description="作品信息")
    chapter_outline: str = Field(default="", description="本章大纲")
    previous_chapters: str = Field(default="", description="前文回顾")


class EditorScoresInput(BaseModel):
    outline_fidelity: int = Field(default=0, ge=0, le=10, description="大纲忠实度 1-10")
    plot_coherence: int = Field(default=0, ge=0, le=10, description="情节连贯性 1-10")
    character_consistency: int = Field(default=0, ge=0, le=10, description="人物一致性 1-10")
    detail_richness: int = Field(default=0, ge=0, le=10, description="细节与信息量 1-10")
    structure: int = Field(default=0, ge=0, le=10, description="章节结构 1-10")
    writing_quality: int = Field(default=0, ge=0, le=10, description="文笔与可读性 1-10")


class SubmitEditorEvaluationInput(BaseModel):
    scores: EditorScoresInput = Field(default_factory=EditorScoresInput)
    total_score: int = Field(default=0, ge=0, le=60, description="总分 0-60")
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ReaderScoresInput(BaseModel):
    hook: int = Field(default=0, ge=0, le=10, description="吸引力 1-10")
    emotional_tension: int = Field(default=0, ge=0, le=10, description="情绪张力 1-10")
    character_immersion: int = Field(default=0, ge=0, le=10, description="角色代入 1-10")
    payoff_and_expectation: int = Field(default=0, ge=0, le=10, description="爽点/期待感 1-10")
    reading_pace: int = Field(default=0, ge=0, le=10, description="节奏体验 1-10")
    retention_intent: int = Field(default=0, ge=0, le=10, description="追更意愿 1-10")


class SubmitReaderEvaluationInput(BaseModel):
    scores: ReaderScoresInput = Field(default_factory=ReaderScoresInput)
    total_score: int = Field(default=0, ge=0, le=60, description="总分 0-60")
    strengths: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


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


# ── 工具实现 ──


@tool(args_schema=ReadChapterForEvalInput)
def read_chapter_for_eval(work_id: str, chapter_number: int, config: RunnableConfig) -> str:
    """读取要评估的章节正文。评估前必须先调用此工具。"""
    from app.models.work_model import Chapter

    db = _get_db(config)
    chapter = db.query(Chapter).filter_by(
        work_id=work_id, chapter_number=chapter_number
    ).first()
    if not chapter:
        return f"第{chapter_number}章不存在。"
    if not chapter.content:
        return f"第{chapter_number}章「{chapter.title}」暂无正文内容。"

    return f"第{chapter.chapter_number}章「{chapter.title}」\n\n{chapter.content}"


@tool(args_schema=ReadChapterOutlineForEvalInput)
def read_chapter_outline_for_eval(work_id: str, chapter_number: int, config: RunnableConfig) -> str:
    """读取本章的大纲节点信息，用于评估正文是否偏离大纲。"""
    from app.models.work_model import Work
    from app.services.work_service import WorkService

    db = _get_db(config)
    work = db.query(Work).filter_by(id=work_id).first()
    if not work:
        return f"作品 {work_id} 不存在。"

    chapter_outline = WorkService._find_chapter_outline(work.outline_tree, chapter_number)
    return chapter_outline or f"第{chapter_number}章未找到对应的大纲节点。"


@tool(args_schema=ReadPreviousChaptersForEvalInput)
def read_previous_chapters_for_eval(work_id: str, chapter_number: int, limit: int, config: RunnableConfig) -> str:
    """读取前几章的正文摘要，用于评估上下文连贯性。"""
    from app.models.work_model import Chapter

    db = _get_db(config)

    prev_chapters = (
        db.query(Chapter)
        .filter_by(work_id=work_id)
        .filter(Chapter.chapter_number < chapter_number)
        .filter(Chapter.content != "")
        .order_by(Chapter.chapter_number.desc())
        .limit(limit)
        .all()
    )
    prev_chapters.reverse()

    if not prev_chapters:
        return "这是第一章，暂无前文。"

    parts = []
    for ch in prev_chapters:
        summary = ch.content[:800] + ("..." if len(ch.content) > 800 else "")
        parts.append(f"--- 第{ch.chapter_number}章 {ch.title} ---\n{summary}")

    return "\n\n".join(parts)


def _format_role_eval_summary(role_label: str, payload: dict) -> str:
    issues = "；".join(payload["issues"][:3]) if payload["issues"] else "暂无明显问题"
    suggestions = "；".join(payload["suggestions"][:3]) if payload["suggestions"] else "暂无建议"
    return f"{role_label}评分：{payload['total_score']}/60。问题：{issues}。建议：{suggestions}"


def _payload_from_tool_calls(tool_calls: Any, expected_name: str) -> dict:
    """从 LLM tool_calls 中提取指定工具的参数字典。"""
    if not tool_calls:
        raise ValueError(f"模型未调用 {expected_name} 工具")
    for tc in tool_calls:
        name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
        if name != expected_name:
            continue
        args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", None)
        if hasattr(args, "model_dump"):
            args = args.model_dump()
        if not isinstance(args, dict):
            raise ValueError(f"{expected_name} 工具参数必须是对象")
        scores = args.get("scores")
        if scores is not None and hasattr(scores, "model_dump"):
            args = {**args, "scores": scores.model_dump()}
        return args
    raise ValueError(f"模型未调用 {expected_name} 工具")


def _validate_submit_payload(payload: dict, role_label: str) -> str | None:
    """校验 submit_*_evaluation 的入参是否为有效实参。

    返回:
      - None: 校验通过
      - str: 自然语言错误描述
    """
    if not isinstance(payload, dict):
        return f"{role_label}评估提交失败：提交参数不是有效对象。请填写完整评分后重新提交。"

    scores = payload.get("scores")
    total_score = payload.get("total_score")
    strengths = payload.get("strengths")
    issues = payload.get("issues")
    suggestions = payload.get("suggestions")

    if not isinstance(scores, dict) or not scores:
        return (
            f"{role_label}评估提交失败：缺少 scores 评分明细。"
            "请填写 6 个评分维度（每项 1-10 分）后再提交。"
        )

    score_values: list[int] = []
    for v in scores.values():
        if not isinstance(v, int):
            return (
                f"{role_label}评估提交失败：scores 中包含非数字分值。"
                "请确保每个维度都是 1-10 的整数。"
            )
        if not 0 <= v <= 10:
            return f"{role_label}评估提交失败：scores 分值超出范围。请确保每个维度都是 0-10 的整数。"
        score_values.append(v)

    if not isinstance(total_score, int):
        return (
            f"{role_label}评估提交失败：total_score 不是有效数字。"
            "请提供 0-60 的总分。"
        )
    if not 0 <= total_score <= 60:
        return f"{role_label}评估提交失败：total_score 超出范围。请提供 0-60 的总分。"

    for field_name, value in (
        ("strengths", strengths),
        ("issues", issues),
        ("suggestions", suggestions),
    ):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return f"{role_label}评估提交失败：{field_name} 必须是字符串数组。"

    # 典型“没填实参”场景：全部走默认值（全 0，且文本反馈为空）
    if score_values and all(v == 0 for v in score_values) and total_score == 0:
        return (
            f"{role_label}评估提交失败：检测到未填写评分实参（所有维度与总分均为 0）。"
            "请先完成每个维度打分，并补充问题与建议后再提交。"
        )

    if not issues and not suggestions:
        return (
            f"{role_label}评估提交失败：缺少问题与建议。"
            "请至少提供 1 条问题或 1 条改进建议后再提交。"
        )

    return None


async def _run_scoring_via_tool_calling(
    *,
    template_name: str,
    submit_tool: Any,
    submit_tool_name: str,
    role_label: str,
    emit_event: str,
    prompt_vars: dict[str, str],
    config: RunnableConfig,
) -> str:
    """通过 bind_tools + submit_* 工具调用完成单视角打分。"""
    from langchain_core.messages import HumanMessage

    from app.services.supervisor.sub_agent_base import get_llm

    emit = _get_emit(config)

    template = (PROMPT_DIR / template_name).read_text(encoding="utf-8")
    prompt_text = PromptTemplate.from_template(template).format(**prompt_vars)

    llm = get_llm(temperature=0.2, streaming=False)
    llm_with_tools = llm.bind_tools([submit_tool])

    response = await llm_with_tools.ainvoke([HumanMessage(content=prompt_text)])
    payload = _payload_from_tool_calls(getattr(response, "tool_calls", None), submit_tool_name)

    validation_error = _validate_submit_payload(payload, role_label)
    if validation_error:
        raise ValueError(validation_error)

    emit(emit_event, payload)
    return _format_role_eval_summary(role_label, payload)


@tool(args_schema=SubmitEditorEvaluationInput)
def submit_editor_evaluation(
    scores: EditorScoresInput,
    total_score: int,
    strengths: list[str] | None = None,
    issues: list[str] | None = None,
    suggestions: list[str] | None = None,
) -> str:
    """提交编辑视角评估结果。完成全部维度打分后必须调用此工具，勿输出裸 JSON 文本。"""
    payload = {
        "scores": scores.model_dump(),
        "total_score": total_score,
        "strengths": strengths or [],
        "issues": issues or [],
        "suggestions": suggestions or [],
    }
    validation_error = _validate_submit_payload(payload, "编辑视角")
    if validation_error:
        raise ValueError(validation_error)
    return _format_role_eval_summary("编辑视角", payload)


@tool(args_schema=SubmitReaderEvaluationInput)
def submit_reader_evaluation(
    scores: ReaderScoresInput,
    total_score: int,
    strengths: list[str] | None = None,
    issues: list[str] | None = None,
    suggestions: list[str] | None = None,
) -> str:
    """提交读者视角评估结果。完成全部维度打分后必须调用此工具，勿输出裸 JSON 文本。"""
    payload = {
        "scores": scores.model_dump(),
        "total_score": total_score,
        "strengths": strengths or [],
        "issues": issues or [],
        "suggestions": suggestions or [],
    }
    validation_error = _validate_submit_payload(payload, "读者视角")
    if validation_error:
        raise ValueError(validation_error)
    return _format_role_eval_summary("读者视角", payload)


async def _evaluate_as_editor_coroutine(
    chapter_content: str,
    story_info: str = "",
    chapter_outline: str = "",
    previous_chapters: str = "",
    config: RunnableConfig = None,
) -> str:
    """以编辑视角评估章节质量（评分结果通过 submit_editor_evaluation 工具提交）。"""
    return await _run_scoring_via_tool_calling(
        template_name="agent_evaluate_editor.txt",
        submit_tool=submit_editor_evaluation,
        submit_tool_name="submit_editor_evaluation",
        role_label="编辑视角",
        emit_event="evaluation_editor_done",
        prompt_vars={
            "story_info": story_info,
            "chapter_outline": chapter_outline or "（未找到本章大纲）",
            "chapter_title": "待评估章节",
            "chapter_content": chapter_content,
            "previous_chapters": previous_chapters,
        },
        config=config,
    )


async def _evaluate_as_reader_coroutine(
    chapter_content: str,
    story_info: str = "",
    chapter_outline: str = "",
    previous_chapters: str = "",
    config: RunnableConfig = None,
) -> str:
    """以读者视角评估章节质量（评分结果通过 submit_reader_evaluation 工具提交）。"""
    return await _run_scoring_via_tool_calling(
        template_name="agent_evaluate_reader.txt",
        submit_tool=submit_reader_evaluation,
        submit_tool_name="submit_reader_evaluation",
        role_label="读者视角",
        emit_event="evaluation_reader_done",
        prompt_vars={
            "story_info": story_info,
            "chapter_outline": chapter_outline or "（未找到本章大纲）",
            "chapter_title": "待评估章节",
            "chapter_content": chapter_content,
            "previous_chapters": previous_chapters,
        },
        config=config,
    )


evaluate_as_editor = StructuredTool.from_function(
    func=None,
    coroutine=_evaluate_as_editor_coroutine,
    name="evaluate_as_editor",
    description="以编辑视角评估章节质量。从结构、节奏、人物一致性等专业维度给出评分和改进建议。",
    args_schema=EvaluateAsEditorInput,
)

evaluate_as_reader = StructuredTool.from_function(
    func=None,
    coroutine=_evaluate_as_reader_coroutine,
    name="evaluate_as_reader",
    description="以读者视角评估章节质量。从代入感、悬念、可读性等体验维度给出评分和改进建议。",
    args_schema=EvaluateAsReaderInput,
)


# ── 导出工具列表 ──

EVALUATION_TOOLS = [
    read_chapter_for_eval,
    read_chapter_outline_for_eval,
    read_previous_chapters_for_eval,
    evaluate_as_editor,
    evaluate_as_reader,
]
