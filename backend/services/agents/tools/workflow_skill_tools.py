"""创作技能、完整参考规则与文本工作记录；规则读取工具不调用模型。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

from models.chapter import Chapter
from models.node import Node
from models.work import CanvasWork

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"
REFERENCE_ROOT = SKILLS_ROOT / "references"
WORKFLOW_SKILLS = {
    "bootstrap-novel": ("premise_architect.txt",),
    "design-worldbuilding": ("worldbuilding.txt",),
    "design-characters": ("character_design.txt",),
    "plan-outline": ("outline_plan.txt",),
    "plan-story-structure": ("story_structure.txt", "chapter_plan.txt"),
    "plan-chapter-scenes": ("scene_plan.txt",),
    "write-chapter": ("scene_plan.txt", "chapter_writer.txt", "chapter_length_advice.txt",
                      "chapter_revision_decision.txt", "chapter_local_edit.txt", "chapter_replan.txt",
                      "chapter_rewrite.txt", "summary.txt"),
    "revise-chapter": ("existing_chapter_revision.txt", "chapter_revision_decision.txt",
                       "chapter_local_edit.txt", "chapter_rewrite.txt", "revision.txt"),
    "humanize-fiction": ("fiction_humanizer.txt", "humanizer_agent.txt"),
    "evaluate-fiction": (),  # 评审规则由独立 Reviewer 按视角加载；旧参考文件保留。
    "maintain-story-memory": ("summary.txt", "story_memory.txt"),
    "apply-research": ("research_application.txt",),
}


def _json(**data):
    return json.dumps(data, ensure_ascii=False)


def _context():
    from services.agents.supervisor import get_context
    return get_context()


def _get_db():
    from database import SessionLocal
    return SessionLocal()


class LoadSkillInput(BaseModel):
    skill_name: str = Field(description="工作流技能名称")
    reason: str | None = None


class ReadReferenceInput(LoadSkillInput):
    reference_name: str = Field(description="load_workflow_skill 返回的 references 中的文件名")


async def _load_workflow_skill(skill_name, reason=None):
    if skill_name not in WORKFLOW_SKILLS:
        return _json(success=False, error="未知工作流技能")
    return _json(success=True, skill_name=skill_name,
                 skill_content=(SKILLS_ROOT / skill_name / "SKILL.md").read_text(encoding="utf-8"),
                 references=list(WORKFLOW_SKILLS[skill_name]))


async def _read_skill_reference(skill_name, reference_name, reason=None):
    if reference_name not in WORKFLOW_SKILLS.get(skill_name, ()):
        return _json(success=False, error="参考文件未在该技能中注册")
    return _json(success=True, skill_name=skill_name, reference_name=reference_name,
                 usage="将完整参考规则作为当前阶段的质量标准。Supervisor 负责规划、评审决策和记忆，阅读评审通过 run_review_agent，正文通过 run_writing_agent 委派 Writer 独立生成并保存；章节笔记通过 save_chapter_notes 保存，最终回复通过 respond_to_user。",
                 content=(REFERENCE_ROOT / reference_name).read_text(encoding="utf-8"))


class SaveChapterNotesInput(BaseModel):
    chapter_node_id: str
    notes: str = Field(description="完整章节笔记：事实摘要、作者要求、创作设计、连续性数据；合并已有条目后整体保存")
    expected_content_sha256: str = Field(description="read_node_content 返回的 content_sha256")
    expected_notes_sha256: str | None = Field(default=None, description="read_chapter_notes 返回的 notes_sha256；已有笔记时用于防止并发覆盖")
    reason: str | None = None

    @model_validator(mode="after")
    def notes_required(self):
        if not (self.notes and self.notes.strip()):
            raise ValueError("章节笔记不能为空")
        if not self.chapter_node_id or not self.expected_content_sha256:
            raise ValueError("保存笔记需要 chapter_node_id 和 expected_content_sha256")
        return self


async def _save_chapter_notes(chapter_node_id, notes, expected_content_sha256, expected_notes_sha256=None, reason=None):
    work_id = _context().get("work_id")
    if not work_id:
        return _json(success=False, error="当前会话未绑定作品")
    with _get_db() as db:
        work = db.query(CanvasWork).filter_by(id=work_id).with_for_update().first()
        if work is None:
            return _json(success=False, error="作品不存在")
        node = db.query(Node).filter_by(id=chapter_node_id, work_id=work_id, type="chapter").with_for_update().first()
        if node is None:
            return _json(success=False, error="章节不属于当前作品")
        if hashlib.sha256((node.content or "").encode("utf-8")).hexdigest() != expected_content_sha256:
            return _json(success=False, error="正文已变化，请回读最新正文后重新整理笔记")
        chapter = db.query(Chapter).filter_by(node_id=node.id).first()
        current_notes = chapter.notes if chapter else ""
        if expected_notes_sha256 is not None and hashlib.sha256((current_notes or "").encode("utf-8")).hexdigest() != expected_notes_sha256:
            return _json(success=False, error_code="notes_changed", error="章节笔记已变化，请重新读取后合并保存")
        if chapter is None:
            chapter = Chapter(work_id=work_id, node_id=node.id, title=node.title, content=node.content or "")
            db.add(chapter)
        old_notes = current_notes or ""
        title = node.title or ""
        chapter.notes = notes
        notes_changed = notes != old_notes
        db.commit()
        result = _json(success=True, notes_saved=True)
    emit = _context().get("emit")
    if emit and notes_changed:
        from services.chapter_edit_service import build_content_diff
        diff = build_content_diff(old_notes, notes)
        if diff.get("hunks"):
            new_len = len("".join(notes.split()))
            old_len = len("".join(old_notes.split()))
            await emit("chapter_notes_diff", {
                "node_id": chapter_node_id,
                "chapter_node_id": chapter_node_id,
                "node_type": "chapter",
                "title": title,
                "diff": diff,
                "original_notes": old_notes,
                "current_notes": notes,
                "notes_count": new_len,
                "notes_count_delta": new_len - old_len,
            })
    if emit:
        await emit("nodes_updated", {"action": "chapter_notes", "chapter_node_id": chapter_node_id, "content_changed": False})
    return result


load_workflow_skill = StructuredTool.from_function(coroutine=_load_workflow_skill, name="load_workflow_skill", args_schema=LoadSkillInput,
    description="完整读取创作 Skill 及参考文件目录，由 Supervisor 编排执行。")
read_skill_reference = StructuredTool.from_function(coroutine=_read_skill_reference, name="read_skill_reference", args_schema=ReadReferenceInput,
    description="按技能和文件名完整读取一个阶段的参考规则。规则由 Supervisor 在当前对话中执行。")
save_chapter_notes = StructuredTool.from_function(coroutine=_save_chapter_notes, name="save_chapter_notes", args_schema=SaveChapterNotesInput,
    description="保存完整章节笔记。笔记包含事实摘要、作者要求、创作设计和连续性数据。正文编辑使用 run_writing_agent。")
workflow_skill_tools = [load_workflow_skill, read_skill_reference, save_chapter_notes]


class ListChaptersInput(BaseModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=50)
    reason: str | None = None


class ReadChapterContextInput(BaseModel):
    chapter_numbers: list[int] = Field(min_length=1, max_length=5, description="作品目录中的章节号，一次最多 5 章")
    catalog_revision: str
    reason: str | None = None

    @model_validator(mode="after")
    def validate_numbers(self):
        if any(number < 1 for number in self.chapter_numbers) or len(set(self.chapter_numbers)) != len(self.chapter_numbers):
            raise ValueError("章节号必须是互不重复的正整数")
        return self


class ReadChapterNotesInput(BaseModel):
    chapter_numbers: list[int] = Field(min_length=1, max_length=20, description="作品目录中的章节号，一次最多 20 章")
    catalog_revision: str
    reason: str | None = None

    @model_validator(mode="after")
    def validate_numbers(self):
        if any(number < 1 for number in self.chapter_numbers) or len(set(self.chapter_numbers)) != len(self.chapter_numbers):
            raise ValueError("章节号必须是互不重复的正整数")
        return self


def _catalog(db, work_id):
    from services.chapter_catalog_service import build_chapter_catalog
    return build_chapter_catalog(db, work_id)


async def _list_chapters(offset=0, limit=20, reason=None):
    work_id = _context().get("work_id")
    if not work_id:
        return _json(success=False, error="当前会话未绑定作品")
    with _get_db() as db:
        chapters, revision, issues = _catalog(db, work_id)
        rows = chapters[offset:offset + limit]
        records = {row.node_id: row for row in db.query(Chapter).filter(Chapter.node_id.in_([n.id for n in rows])).all()} if rows else {}
        return _json(success=True, catalog_revision=revision, chapters=[{
            "chapter_number": offset + index + 1, "chapter_node_id": node.id,
            "title": node.title, "has_content": bool(node.content),
            "has_notes": bool((records.get(node.id).notes if records.get(node.id) else "")),
            "content_chars": len(node.content or ""),
            "notes_chars": len(records.get(node.id).notes or "") if records.get(node.id) else 0,
        } for index, node in enumerate(rows)], total=len(chapters),
            has_more=offset + len(rows) < len(chapters), next_offset=offset + len(rows), issues=issues)


def _select_chapters(db, work_id, chapter_numbers, catalog_revision):
    chapters, revision, _ = _catalog(db, work_id)
    if revision != catalog_revision:
        return None, _json(success=False, error_code="catalog_changed", error="章节目录已变化，请重新读取目录")
    by_number = {index: node for index, node in enumerate(chapters, 1)}
    missing = [number for number in chapter_numbers if number not in by_number]
    if missing:
        return None, _json(success=False, error_code="chapter_not_found", error="章节号不存在", chapter_numbers=missing)
    return [(number, by_number[number]) for number in chapter_numbers], None


async def _read_chapter_context(chapter_numbers, catalog_revision, reason=None):
    work_id = _context().get("work_id")
    if not work_id:
        return _json(success=False, error="当前会话未绑定作品")
    with _get_db() as db:
        selected, error = _select_chapters(db, work_id, chapter_numbers, catalog_revision)
        if error:
            return error
        return _json(success=True, catalog_revision=catalog_revision, chapters=[{
            "chapter_number": number, "chapter_node_id": node.id, "title": node.title,
            "content": node.content or "",
            "content_sha256": hashlib.sha256((node.content or "").encode("utf-8")).hexdigest(),
        } for number, node in selected])


async def _read_chapter_notes(chapter_numbers, catalog_revision, reason=None):
    work_id = _context().get("work_id")
    if not work_id:
        return _json(success=False, error="当前会话未绑定作品")
    with _get_db() as db:
        selected, error = _select_chapters(db, work_id, chapter_numbers, catalog_revision)
        if error:
            return error
        records = {row.node_id: row for row in db.query(Chapter).filter(Chapter.node_id.in_([node.id for _, node in selected])).all()}
        result = []
        for number, node in selected:
            notes = records.get(node.id).notes if records.get(node.id) else ""
            result.append({"chapter_number": number, "chapter_node_id": node.id, "title": node.title,
                           "notes": notes or "", "has_notes": bool(notes),
                           "notes_sha256": hashlib.sha256((notes or "").encode("utf-8")).hexdigest(),
                           "content_sha256": hashlib.sha256((node.content or "").encode("utf-8")).hexdigest()})
        return _json(success=True, catalog_revision=catalog_revision, chapters=result)


read_chapter_context = StructuredTool.from_function(
    coroutine=_read_chapter_context, name="read_chapter_context", args_schema=ReadChapterContextInput,
    description="按作品目录章节号完整读取正文；一次必须明确选择 1-5 章，不附带笔记或其他章节。")
list_chapters = StructuredTool.from_function(coroutine=_list_chapters, name="list_chapters", args_schema=ListChaptersInput,
    description="分页读取作品章节目录，不返回正文或笔记；使用 catalog_revision 读取正文和笔记。")
read_chapter_notes = StructuredTool.from_function(coroutine=_read_chapter_notes, name="read_chapter_notes", args_schema=ReadChapterNotesInput,
    description="按作品目录章节号完整读取章节笔记；一次必须明确选择 1-20 章，不附带正文。")
workflow_skill_tools.extend([list_chapters, read_chapter_context, read_chapter_notes])
