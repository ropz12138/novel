"""WritingExpertAgent 工具集

写作专家微咨询子 Agent 的工具。
"""

from __future__ import annotations

import logging

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Tool input schemas ──


class QueryWritingLibraryInput(BaseModel):
    problem_type: str = Field(description="问题类型：conflict_event/hook_design/pacing_fix/character_tension/dialogue_upgrade")
    genre_tags: list[str] = Field(description="题材标签列表")


class GenerateAdviceInput(BaseModel):
    problem_type: str = Field(description="问题类型")
    genre_tags: list[str] = Field(description="题材标签列表")
    constraints: list[str] = Field(default_factory=list, description="约束条件")
    chapter_goal: str = Field(default="", description="章节目标")
    chapter_number: int | None = Field(default=None, description="目标章节号")
    count: int = Field(default=8, description="候选建议数量")


# ── Helpers ──


def _get_db(config: RunnableConfig):
    from sqlalchemy.orm import Session
    configurable = config.get("configurable", {})
    db = configurable.get("db")
    if db is None:
        raise ValueError("db Session 未在 configurable 中提供")
    return db


def _get_emit(config: RunnableConfig):
    configurable = config.get("configurable", {})
    return configurable.get("emit", lambda event, data: None)


# ── 工具实现 ──


@tool(args_schema=QueryWritingLibraryInput)
def query_writing_library(problem_type: str, genre_tags: list[str], config: RunnableConfig) -> str:
    """查询写作技巧库中与当前问题和题材匹配的技巧。"""
    from app.services.writing_expert_service import WritingExpertService

    db = _get_db(config)
    emit = _get_emit(config)

    advice = WritingExpertService.advise(
        db=db,
        problem_type=problem_type,
        genre_tags=genre_tags,
        constraints=[],
        chapter_goal="",
        chapter_number=None,
        count=8,
    )

    options_text = []
    for opt in advice.options:
        options_text.append(f"- {opt.get('event_name', '')}：{opt.get('how_to_use_in_this_chapter', '')}")

    emit("writing_expert_library_queried", {"count": len(options_text)})
    return f"找到 {len(options_text)} 条相关写作技巧：\n" + "\n".join(options_text)


async def _generate_advice_coroutine(
    problem_type: str,
    genre_tags: list[str],
    constraints: list[str] | None = None,
    chapter_goal: str = "",
    chapter_number: int | None = None,
    count: int = 8,
    config: RunnableConfig = None,
) -> str:
    """生成针对当前问题的具体写作建议。"""
    from json import dumps
    from app.services.writing_expert_service import WritingExpertService

    db = _get_db(config)
    emit = _get_emit(config)

    advice = WritingExpertService.advise(
        db=db,
        problem_type=problem_type,
        genre_tags=genre_tags,
        constraints=constraints or [],
        chapter_goal=chapter_goal,
        chapter_number=chapter_number,
        count=count,
    )

    payload = {
        "problem_type": problem_type,
        "genre_tags": genre_tags,
        "options": advice.options,
        "recommended_pick": advice.recommended_pick,
        "apply_prompt_for_chapter_agent": advice.apply_prompt_for_chapter_agent,
    }

    emit("writing_expert_done", payload)

    recommended = advice.recommended_pick
    summary = (
        f"推荐方案：{recommended.get('event_name', '（无）')}。\n"
        f"共 {len(advice.options)} 条候选方案。\n"
        f"章节改写指令：{advice.apply_prompt_for_chapter_agent}"
    )
    return summary


from langchain_core.tools import StructuredTool

generate_advice = StructuredTool.from_function(
    func=None,
    coroutine=_generate_advice_coroutine,
    name="generate_advice",
    description="生成针对当前写作问题的具体建议方案。返回候选方案和推荐首选。",
    args_schema=GenerateAdviceInput,
)


# ── 导出工具列表 ──

WRITING_EXPERT_TOOLS = [
    query_writing_library,
    generate_advice,
]
