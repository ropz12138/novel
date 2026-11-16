"""只读情节参考子 Agent：从当前用户上传小说中检索章节原文。"""
from __future__ import annotations

import database

import json
import logging
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from models.research import ResearchJob, ResearchTextVersion
from services.research_chapters import list_indexed_chapters, read_indexed_chapter


logger = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "reference_agent_system.txt"




def _current_user_id() -> str:
    from services.agents.supervisor import get_context
    user_id = get_context().get("user_id")
    if not user_id:
        raise ValueError("当前会话缺少用户身份")
    return user_id


def reference_agent_tool(user_id: str | None):
    if not user_id:
        return None
    with database.open_db() as db:
        rows = (
            db.query(ResearchJob.original_filename, ResearchJob.id)
            .join(ResearchTextVersion, ResearchTextVersion.id == ResearchJob.active_version_id)
            .filter(
                ResearchJob.user_id == user_id,
                ResearchTextVersion.job_id == ResearchJob.id,
                ResearchTextVersion.kind == "cleaned",
            )
            .order_by(ResearchJob.original_filename.asc(), ResearchJob.id.asc())
            .all()
        )
    if not rows:
        return None
    catalog = "\n".join(f"{filename} {job_id}" for filename, job_id in rows)
    return run_reference_agent.model_copy(update={
        "description": f"{run_reference_agent.description}\n可检索小说：\n{catalog}",
    })


class ReferenceAgentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    planning_need: str = Field(min_length=1, description="要检索的具体材料，例如章节范围、场景或桥段")
    current_story_context: str = Field(min_length=1, description="帮助定位检索范围的当前作品事实")
    desired_experience: str = Field(min_length=1, description="希望从上传小说中找到的材料类型与强度")
    research_work_ids: list[str] = Field(min_length=1, description="要检索的当前用户上传小说 ID")
    candidate_count: int = Field(default=3, ge=1, le=5, description="最多返回的章节数量")
    reason: str | None = None


class ChapterLocator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str
    section_index: int = Field(ge=0)


class ListReferenceChaptersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_ids: list[str] = Field(min_length=1)


class SearchReferenceChaptersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_ids: list[str] = Field(min_length=1)
    query_terms: list[str] = Field(min_length=1, description="用于定位事件的多个具体动作、场景或关系词")


class ReadReferenceChaptersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapters: list[ChapterLocator] = Field(min_length=1)


class ReferenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    work_id: str
    version_id: str
    section_index: int = Field(ge=0)


class ReferenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[ReferenceSource] = Field(min_length=1)


def _owned_jobs(work_ids: list[str]) -> list[ResearchJob]:
    from services.agents.supervisor import get_context

    user_id = _current_user_id()
    requested = list(dict.fromkeys(work_ids))
    allowed = get_context().get("reference_work_ids")
    if allowed is not None and any(work_id not in allowed for work_id in requested):
        raise ValueError("小说超出本次情节参考范围")
    with database.open_db() as db:
        rows = db.query(ResearchJob).filter(
            ResearchJob.user_id == user_id,
            ResearchJob.id.in_(requested),
        ).all()
        by_id = {row.id: row for row in rows}
        if any(work_id not in by_id for work_id in requested):
            raise ValueError("小说需要属于当前用户")
        return [by_id[work_id] for work_id in requested]


def _active_cleaned_version(db, job: ResearchJob) -> ResearchTextVersion:
    version = db.query(ResearchTextVersion).filter_by(
        id=job.active_version_id,
        job_id=job.id,
        kind="cleaned",
    ).first()
    if version is None:
        raise ValueError(f"小说《{job.original_filename}》尚无可按章读取的清洗版本")
    return version


def _list_reference_chapters_sync(work_ids: list[str]) -> str:
    jobs = _owned_jobs(work_ids)
    chapters = []
    with database.open_db() as db:
        for detached in jobs:
            job = db.query(ResearchJob).filter_by(id=detached.id).one()
            version = _active_cleaned_version(db, job)
            for chapter in list_indexed_chapters(version):
                chapters.append({
                    "work_id": job.id,
                    "source_filename": job.original_filename,
                    "version_id": version.id,
                    **chapter,
                })
    return json.dumps({"success": True, "chapters": chapters}, ensure_ascii=False)


def _search_reference_chapters_sync(work_ids: list[str], query_terms: list[str]) -> str:
    terms = list(dict.fromkeys(term.strip() for term in query_terms if term.strip()))
    if not terms:
        raise ValueError("检索词不能为空")
    jobs = _owned_jobs(work_ids)
    matches = []
    with database.open_db() as db:
        for detached in jobs:
            job = db.query(ResearchJob).filter_by(id=detached.id).one()
            version = _active_cleaned_version(db, job)
            for chapter in list_indexed_chapters(version):
                content = read_indexed_chapter(version, chapter["section_index"])["content"]
                matched = [term for term in terms if term in content]
                if matched:
                    matches.append({
                        "work_id": job.id,
                        "source_filename": job.original_filename,
                        "version_id": version.id,
                        "section_index": chapter["section_index"],
                        "heading": chapter["heading"],
                        "matched_terms": matched,
                    })
    return json.dumps({"success": True, "matches": matches}, ensure_ascii=False)


def _read_reference_chapters_sync(chapters: list[dict] | list[ChapterLocator]) -> str:
    user_id = _current_user_id()
    locators = [item if isinstance(item, ChapterLocator) else ChapterLocator.model_validate(item)
                for item in chapters]
    result = []
    with database.open_db() as db:
        for locator in locators:
            row = db.query(ResearchTextVersion, ResearchJob).join(
                ResearchJob, ResearchTextVersion.job_id == ResearchJob.id,
            ).filter(
                ResearchTextVersion.id == locator.version_id,
                ResearchTextVersion.kind == "cleaned",
                ResearchJob.user_id == user_id,
            ).first()
            if row is None:
                raise ValueError("章节版本需要属于当前用户的清洗小说")
            version, job = row
            chapter = read_indexed_chapter(version, locator.section_index)
            result.append({
                "work_id": job.id,
                "source_filename": job.original_filename,
                "version_id": version.id,
                **chapter,
            })
    return json.dumps({"success": True, "chapters": result}, ensure_ascii=False)


list_reference_chapters = StructuredTool.from_function(
    func=_list_reference_chapters_sync,
    name="list_reference_chapters",
    args_schema=ListReferenceChaptersInput,
    description="列出指定上传小说的全部清洗章节目录，返回可供检索和完整读取的章节定位信息。",
)
search_reference_chapters = StructuredTool.from_function(
    func=_search_reference_chapters_sync,
    name="search_reference_chapters",
    args_schema=SearchReferenceChaptersInput,
    description="用多个具体词检索指定上传小说，返回命中的作品、清洗版本和章节位置。",
)
read_reference_chapters = StructuredTool.from_function(
    func=_read_reference_chapters_sync,
    name="read_reference_chapters",
    args_schema=ReadReferenceChaptersInput,
    description="按清洗版本与章节序号读取完整章节正文，用于核验候选事件及其上下文。",
)


def _validate_sources(result: ReferenceResult, allowed_work_ids: set[str]) -> list[dict]:
    seen: set[tuple[str, int]] = set()
    loaded: list[dict] = []
    with database.open_db() as db:
        for source in result.sources:
            key = (source.version_id, source.section_index)
            if key in seen:
                raise ValueError("同一章节重复提交")
            seen.add(key)
            if source.work_id not in allowed_work_ids:
                raise ValueError("章节出处超出本次指定小说")
            row = db.query(ResearchTextVersion, ResearchJob).join(
                ResearchJob, ResearchTextVersion.job_id == ResearchJob.id,
            ).filter(
                ResearchTextVersion.id == source.version_id,
                ResearchTextVersion.job_id == source.work_id,
                ResearchJob.user_id == _current_user_id(),
            ).first()
            if row is None:
                raise ValueError("章节出处不属于当前用户")
            chapter = read_indexed_chapter(row[0], source.section_index)
            loaded.append({
                "work_id": source.work_id,
                "version_id": source.version_id,
                "section_index": source.section_index,
                "heading": chapter["heading"],
                "content": chapter["content"],
            })
    return loaded


async def _invoke_reference_agent(*, task: dict, allowed_work_ids: set[str], child_task=None) -> dict:
    from services.agents.supervisor import get_context, reset_context, set_context

    submitted: list[dict] = []

    async def submit_retrieved_chapters(**kwargs):
        try:
            result = ReferenceResult.model_validate(kwargs)
            if len(result.sources) > task["candidate_count"]:
                raise ValueError("章节数量超过 Supervisor 的请求")
            loaded = _validate_sources(result, allowed_work_ids)
        except ValueError as exc:
            return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
        submitted[:] = [{
            "text": "\n\n".join(item["content"] for item in loaded),
            "sources": [{key: item[key] for key in ("work_id", "version_id", "section_index", "heading")} for item in loaded],
        }]
        return json.dumps({"success": True, "submitted": True}, ensure_ascii=False)

    submit = StructuredTool.from_function(
        coroutine=submit_retrieved_chapters,
        name="submit_retrieved_chapters",
        args_schema=ReferenceResult,
        return_direct=True,
        description="提交已读取章节的出处。程序按出处附上清洗版原文。",
    )
    parent = get_context()
    isolated = {key: parent[key] for key in ("user_id", "work_id", "session_id", "model_pref") if key in parent}
    isolated["agent_role"] = "reference_agent"
    isolated["reference_work_ids"] = frozenset(allowed_work_ids)
    token = set_context(isolated)
    try:
        from services.agents.subagent_runtime import invoke_isolated_subagent
        await invoke_isolated_subagent(
            name='reference_agent', system_prompt=PROMPT_PATH.read_text(encoding='utf-8'),
            task=task, tools=[list_reference_chapters, search_reference_chapters, read_reference_chapters, submit],
            completion_tool_name='submit_retrieved_chapters', child_task=child_task,
        )
    finally:
        reset_context(token)
    if len(submitted) != 1:
        raise ValueError("情节参考子 Agent 未提交唯一结果")
    return submitted[0]


async def _run_reference_agent(**kwargs) -> str:
    request = ReferenceAgentInput.model_validate(kwargs)
    try:
        jobs = _owned_jobs(request.research_work_ids)
        task = {
            "planning_need": request.planning_need,
            "current_story_context": request.current_story_context,
            "desired_experience": request.desired_experience,
            "candidate_count": request.candidate_count,
            "available_works": [
                {"work_id": job.id, "source_filename": job.original_filename}
                for job in jobs
            ],
        }
        from services.agents.supervisor import get_context
        emit = get_context().get("emit")
        if emit:
            await emit("stage_start", {"stage": "researching", "label": "情节参考 Agent 正在检索上传小说"})
        from services.agents.run_control import current_run_control
        async def execute(child):
            result = await _invoke_reference_agent(task=task, allowed_work_ids={job.id for job in jobs}, child_task=child)
            return {"success": True, "agent": "reference_agent", **result}
        child = current_run_control().start('reference_agent', None, execute)
        return json.dumps({'success': True, 'status': 'running', 'agent': 'reference_agent', 'task_id': child.id}, ensure_ascii=False)
    except Exception as exc:
        logger.exception("reference agent failed")
        return json.dumps({"success": False, "agent": "reference_agent", "error": str(exc)}, ensure_ascii=False)


run_reference_agent = StructuredTool.from_function(
    coroutine=_run_reference_agent,
    name="run_reference_agent",
    args_schema=ReferenceAgentInput,
    description=("新内容设计与创作的必经检索环节。工具出现在工具集中时，形成具体方案前完成本轮调用。异步派发并立即返回 task_id，完成通知提供结果。只读情节参考子 Agent 检索当前用户指定的上传小说，返回一个合并后的章节原文字段和出处列表。"
                 "完成通知带有章节原文时，Supervisor 阅读后选择、改造并形成最终方案。完成通知只含任务状态时，Supervisor 按当前作品已有事实完成本轮设计与正文。"),
)
