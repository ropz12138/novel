"""只读评审子 Agent：可注册视角，共用完整快照，独立并行提交报告。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from models.node import Node
from services.agent_paragraphs import present_content_record
from services.agents.subagent_runtime import invoke_isolated_subagent

logger = logging.getLogger(__name__)
PROMPT_ROOT = Path(__file__).resolve().parents[1] / "prompts"
REVIEW_PERSPECTIVES = {
    "tired_reader": PROMPT_ROOT / "reviewers" / "tired_reader.txt",
    "ai_taste": PROMPT_ROOT / "reviewers" / "ai_taste.txt",
}


class ReviewAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter_node_ids: list[str] = Field(min_length=1, description="按阅读顺序提供当前作品的章节 UUID，加载完整正文")
    source_node_ids: list[str] = Field(default_factory=list, description="相关前章、人物、设定、笔记 UUID，完整读取作为参考")
    author_requirements: str = Field(min_length=1, description="完整有效的作者要求、题材、文风与偏好")
    review_goal: str = Field(min_length=1, description="本次需要判断的阅读问题与范围")
    perspectives: list[str] = Field(default_factory=lambda: ["tired_reader"], min_length=1,
                                    description="评审视角 ID：tired_reader（劳累读者）、ai_taste（AI 味）；可单独选择或并行评审同一版本")
    reason: str | None = None


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapter_node_id: str
    evidence: str = Field(min_length=1, description="问题位置的连续原文，逐字引用目标正文")
    impact: str = Field(min_length=1, description="该处对当前视角阅读的影响")
    suggestion: str = Field(min_length=1, description="具体修改目标，保留作者要求与故事事实")


class ReviewReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report: str = Field(min_length=1, description="当前视角的阅读结论与依据，可使用 Markdown")
    issues: list[ReviewIssue] = Field(default_factory=list, description="有连续原文定位的问题；结论写在 report 中时留空")


def _load_review_task(request: ReviewAgentInput, work_id: str) -> dict:
    from database import SessionLocal

    with SessionLocal() as db:
        def load(node_ids, *, chapters_only=False):
            result = []
            for node_id in dict.fromkeys(node_ids):
                node = db.query(Node).filter_by(id=node_id, work_id=work_id).first()
                if node is None or (chapters_only and node.type != "chapter"):
                    raise ValueError("评审节点需要属于当前作品，评审目标需要是章节")
                content = node.content or ""
                if chapters_only and not content.strip():
                    raise ValueError("评审目标需要包含正文")
                result.append({"node_id": node.id, "type": node.type, "title": node.title,
                               "content": content,
                               "content_sha256": hashlib.sha256(content.encode()).hexdigest()})
            return result

        reviewer_note_ids = [node.id for node in db.query(Node).filter_by(work_id=work_id, type='reviewer_note')
                             .order_by(Node.sort_order, Node.created_at, Node.id).all()]
        author_notes, chapter_notes = _collected_notes(work_id)
        return {"chapters": load(request.chapter_node_ids, chapters_only=True),
                "sources": load(request.source_node_ids),
                "author_notes": author_notes,
                "chapter_notes": chapter_notes,
                "reviewer_notes": load(reviewer_note_ids),
                "author_requirements": request.author_requirements,
                "review_goal": request.review_goal}


def _collected_notes(work_id: str) -> tuple[list[dict], list[dict]]:
    from services.work_state import snapshot

    author_notes = []
    chapter_notes = []
    for node in snapshot(work_id)["nodes"]:
        if node["type"] == "note":
            author_notes.append({
                "node_id": node["id"], "type": node["type"], "title": node["title"],
                "scope": node.get("scope"), "content": node["content"] or "",
            })
        elif node["type"] == "chapter" and node.get("notes"):
            chapter_notes.append({
                "chapter_node_id": node["id"], "type": "chapter_note", "title": node["title"],
                "scope": "本章节及其后续连续性", "content": node["notes"],
            })
    return author_notes, chapter_notes


def _model_review_task(task: dict) -> dict:
    model = {}
    for key, value in task.items():
        if key in {"chapters", "sources", "author_notes", "chapter_notes", "reviewer_notes"}:
            model[key] = [present_content_record(item) for item in value]
        else:
            model[key] = value
    return model


async def _review_perspective(perspective: str, task: dict) -> dict:
    submitted: list[dict] = []
    target_contents = {chapter["node_id"]: chapter["content"] for chapter in task["chapters"]}

    async def submit_review(**kwargs):
        if submitted:
            raise ValueError("本视角已经提交评审")
        report = ReviewReport.model_validate(kwargs)
        for issue in report.issues:
            if issue.chapter_node_id not in target_contents or issue.evidence not in target_contents[issue.chapter_node_id]:
                raise ValueError("问题证据需要逐字引用所标记目标章节的连续正文")
        submitted.append(report.model_dump())
        return json.dumps({"success": True, "submitted": True}, ensure_ascii=False)

    submit = StructuredTool.from_function(
        coroutine=submit_review, name="submit_review", args_schema=ReviewReport,
        return_direct=True, description="提交当前视角的阅读报告；有连续原文定位的问题写入 issues。",
    )
    try:
        prompt = (PROMPT_ROOT / "reviewer_system.txt").read_text(encoding="utf-8")
        perspective_prompt = REVIEW_PERSPECTIVES[perspective].read_text(encoding="utf-8")
        system_prompt = prompt + "\n\n" + perspective_prompt
        model_task = _model_review_task(task)
        await invoke_isolated_subagent(
            name=f"reviewer_{perspective}", system_prompt=system_prompt,
            task=model_task, tools=[submit],
        )
        if len(submitted) != 1:
            raise ValueError("评审子 Agent 未提交报告")
    except Exception as exc:
        logger.exception("review failed perspective=%s", perspective)
        return {"perspective": perspective, "error": str(exc)}
    return {"perspective": perspective, "report": submitted[0]}


async def _execute_review_agent(**kwargs):
    from services.agents.supervisor import get_context

    request = ReviewAgentInput.model_validate(kwargs)
    work_id = get_context().get("work_id")
    if not work_id:
        return json.dumps({"success": False, "error": "当前会话未绑定作品"}, ensure_ascii=False)
    perspectives = list(dict.fromkeys(request.perspectives))
    if any(name not in REVIEW_PERSPECTIVES for name in perspectives):
        return json.dumps({"success": False, "error": "未知评审视角",
                           "available_perspectives": list(REVIEW_PERSPECTIVES)}, ensure_ascii=False)
    try:
        task = _load_review_task(request, work_id)
    except (ValueError, KeyError) as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    emit = get_context().get("emit")
    if emit:
        await emit("stage_start", {"stage": "reviewing", "label": "评审子 Agent 正在阅读"})
    results = await asyncio.gather(*(_review_perspective(name, task) for name in perspectives))
    try:
        current = _load_review_task(request, work_id)
        if any(current[key] != task[key] for key in (
                'chapters', 'sources', 'author_notes', 'chapter_notes', 'reviewer_notes')):
            raise ValueError('评审目标、引用来源、作者笔记或专用评审笔记已变化，请基于最新版本重新评审')
    except ValueError as exc:
        return json.dumps({'success': False, 'error': str(exc)}, ensure_ascii=False)
    reports = [result for result in results if "report" in result]
    errors = [result for result in results if "error" in result]
    return json.dumps({"success": not errors,
                       "chapters": [{"node_id": chapter["node_id"],
                                     "content_sha256": chapter["content_sha256"]}
                                    for chapter in task["chapters"]],
                       "reports": reports, "errors": errors}, ensure_ascii=False)


async def _run_review_agent(**kwargs):
    from services.agents.run_control import current_run_control
    request = ReviewAgentInput.model_validate(kwargs)
    # 输入归属校验在派发前完成。
    from services.agents.supervisor import get_context
    work_id = get_context().get('work_id')
    if not work_id:
        return json.dumps({'success': False, 'error': '当前会话未绑定作品'}, ensure_ascii=False)
    try:
        _load_review_task(request, work_id)
        if any(name not in REVIEW_PERSPECTIVES for name in request.perspectives):
            raise ValueError('未知评审视角')
    except ValueError as exc:
        return json.dumps({'success': False, 'error': str(exc)}, ensure_ascii=False)

    async def execute(child):
        current = dict(kwargs)
        while True:
            additions = child.take_instructions()
            if additions:
                current['review_goal'] += '\n\nSupervisor 补充要求：\n' + '\n\n'.join(additions)
            result = json.loads(await _execute_review_agent(**current))
            if not child.instructions:
                return result

    child = current_run_control().start('reviewer', None, execute)
    return json.dumps({'success': True, 'status': 'running', 'agent': 'reviewer', 'task_id': child.id}, ensure_ascii=False)


run_review_agent = StructuredTool.from_function(
    coroutine=_run_review_agent, name="run_review_agent", args_schema=ReviewAgentInput,
    description=("异步派发只读评审子 Agent，立即返回 task_id，完成通知提供阅读报告与可选的原文定位问题。"
                 "视角 tired_reader：劳累读者；ai_taste：表达自然度与机械感。可单独调用或并行。提供完整作者要求与相关来源，"
                 "各视角共用同一正文版本并独立提交报告；Supervisor 汇总决定并直接修改正文。"),
)
