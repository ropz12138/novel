"""跨创作功能的 Workflow Skill loader 与可复用专职 Agent Tools。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from models.node import Node
from models.edge import Edge
from models.research import ResearchArtifact, ResearchJob
from models.workflow import WorkflowArtifact
from services.agents.tools import specialist_agent_tools as sat
from services.node_content_write_service import write_node_content


AGENT_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = AGENT_ROOT / "skills"
HUMANIZER_PATH = AGENT_ROOT / "prompts" / "fiction_humanizer.txt"

WORKFLOW_SKILLS = {
    "bootstrap-novel": "bootstrap-novel",
    "design-worldbuilding": "design-worldbuilding",
    "design-characters": "design-characters",
    "plan-outline": "plan-outline",
    "plan-story-structure": "plan-story-structure",
    "write-chapter": "write-chapter",
    "revise-chapter": "revise-chapter",
    "humanize-fiction": "humanize-fiction",
    "evaluate-fiction": "evaluate-fiction",
    "maintain-story-memory": "maintain-story-memory",
    "apply-research": "apply-research",
}


def _get_db():
    return sat._get_db()


def _current_context() -> dict:
    try:
        from services.agents.supervisor import get_context

        return get_context()
    except Exception:
        return {}


class LoadWorkflowSkillInput(BaseModel):
    skill_name: str = Field(description="要完整加载的 Workflow Skill 名称")
    reason: Optional[str] = None


async def _load_workflow_skill(skill_name: str, reason=None) -> str:
    folder = WORKFLOW_SKILLS.get(skill_name)
    if not folder:
        return sat._failure("workflow_skill_loader", f"未注册的 Workflow Skill：{skill_name}", "workflow_skill_not_found")
    try:
        content = (SKILLS_ROOT / folder / "SKILL.md").read_text(encoding="utf-8")
        return sat._envelope(
            status="completed",
            agent="workflow_skill_loader",
            result={"skill_name": skill_name, "skill_content": content},
            gate_code="workflow_skill_loaded",
            passed=True,
        )
    except Exception as exc:
        return sat._failure("workflow_skill_loader", str(exc), "workflow_skill_load_failed")


class AssembleWorkContextInput(BaseModel):
    user_instruction: str = Field(description="用户本轮完整要求")
    target_node_ids: list[str] = Field(default_factory=list, description="本轮明确指定的节点 ID")
    mode: str = Field(default="create", description="create|reverse|continue|revise|cascade|evaluate")
    reason: Optional[str] = None


async def _assemble_work_context(user_instruction: str, target_node_ids=None, mode="create", reason=None) -> str:
    db = _get_db()
    try:
        work_id = _current_context().get("work_id")
        if not work_id:
            return sat._failure("work_context_assembler", "未指定作品ID", "work_not_bound")
        nodes = db.query(Node).filter(Node.work_id == work_id).order_by(Node.type, Node.sort_order, Node.id).all()
        requested = set(target_node_ids or [])
        unavailable = requested - {item.id for item in nodes}
        if unavailable:
            return sat._failure("work_context_assembler", f"目标节点不属于当前作品：{sorted(unavailable)}", "target_node_unavailable")
        payload = {
            "work_id": work_id,
            "mode": mode,
            "user_instruction": user_instruction,
            "target_node_ids": list(target_node_ids or []),
            "nodes": [
                {
                    "id": item.id,
                    "type": item.type,
                    "title": item.title,
                    "content": item.content or "",
                    "scope": item.scope,
                    "sort_order": item.sort_order,
                    "extra_data": item.extra_data or {},
                }
                for item in nodes
            ],
        }
        artifact = sat._create_artifact(work_id, None, "work_context", json.dumps(payload, ensure_ascii=False))
        return sat._envelope(
            status="completed",
            agent="work_context_assembler",
            artifact=artifact,
            result={
                "work_id": work_id,
                "mode": mode,
                "target_node_ids": list(target_node_ids or []),
                "node_count": len(nodes),
                "node_type_counts": {
                    node_type: sum(1 for item in nodes if item.type == node_type)
                    for node_type in sorted({item.type for item in nodes})
                },
            },
            gate_code="work_context_ready",
            passed=True,
        )
    except Exception as exc:
        return sat._failure("work_context_assembler", str(exc), "work_context_failed")
    finally:
        db.close()


class ArtifactReviewInput(BaseModel):
    context_artifact_id: str
    artifact_id: str
    perspective: str = "editor"
    minimum_score: int = Field(default=7, ge=1, le=10)
    reason: Optional[str] = None


async def _review_artifact_quality(context_artifact_id: str, artifact_id: str, perspective="editor", minimum_score=7, reason=None):
    try:
        context = sat._load_artifact(context_artifact_id)
        source = sat._load_artifact(artifact_id)
        result = await sat._invoke_json_agent(
            "quality_review.txt",
            f"======= 完整作品上下文 =======\n{context.content}\n\n======= 审查视角 =======\n{perspective}\n\n======= 完整待审查产物 =======\n{source.content}",
        )
        score = int(result.get("score") or 0)
        issues = result.get("issues") or []
        passed = score >= minimum_score and not any(
            isinstance(item, dict) and item.get("severity") == "major" for item in issues
        )
        artifact = sat._create_artifact(source.work_id, source.chapter_node_id, "quality_review", json.dumps(result, ensure_ascii=False), parent_artifact_id=source.id)
        return sat._envelope(
            status="completed" if passed else "needs_revision",
            agent="quality_review",
            artifact=artifact,
            inputs=[context, source],
            result=result,
            gate_code="quality_passed" if passed else "quality_revision_required",
            passed=passed,
        )
    except Exception as exc:
        return sat._failure("quality_review", str(exc), "quality_review_failed")


class StageChapterInput(BaseModel):
    context_artifact_id: str
    reason: Optional[str] = None


async def _stage_existing_chapter_draft(context_artifact_id: str, reason=None):
    try:
        context = sat._load_artifact(context_artifact_id, "chapter_context")
        data = json.loads(context.content)
        content = str((data.get("target_chapter") or {}).get("content") or "")
        if not content:
            raise ValueError("目标章节正文为空")
        artifact = sat._create_artifact(context.work_id, context.chapter_node_id, "chapter_draft", content, parent_artifact_id=context.id)
        return sat._envelope(status="completed", agent="chapter_stager", artifact=artifact, inputs=[context], result={"word_count": len("".join(content.split())), "source_content_sha256": sat._content_sha256(content)}, gate_code="existing_draft_ready", passed=True)
    except Exception as exc:
        return sat._failure("chapter_stager", str(exc), "existing_draft_failed")


class ExistingRevisionInput(BaseModel):
    context_artifact_id: str
    draft_artifact_id: str
    user_instruction: str
    reason: Optional[str] = None


async def _revise_existing_chapter_draft(context_artifact_id: str, draft_artifact_id: str, user_instruction: str, reason=None):
    try:
        context = sat._load_artifact(context_artifact_id, "chapter_context")
        draft = sat._load_artifact(draft_artifact_id, "chapter_draft")
        preview = await sat._emit_content_preview_start(context)
        result = await sat._invoke_json_agent(
            "existing_chapter_revision.txt",
            f"======= 完整作品上下文 =======\n{context.content}\n\n======= 作者完整要求 =======\n{user_instruction}\n\n======= 完整原文 =======\n{draft.content}",
            content_delta_callback=(
                (lambda delta: sat._emit_content_preview_delta(preview, delta))
                if preview["enabled"] else None
            ),
        )
        content = str(result.get("content") or "")
        if not content:
            raise ValueError("修改结果缺少完整 content")
        await sat._emit_content_preview_complete(preview, content)
        await sat._write_draft_to_existing_chapter(draft.work_id, draft.chapter_node_id, content)
        artifact = sat._create_artifact(draft.work_id, draft.chapter_node_id, "chapter_draft", content, parent_artifact_id=draft.id, version=draft.version + 1)
        public = {key: value for key, value in result.items() if key != "content"}
        public.update({"source_version": draft.version, "result_version": artifact.version, "word_count": len("".join(content.split()))})
        return sat._envelope(status="completed", agent="existing_chapter_revision", artifact=artifact, inputs=[context, draft], result=public, gate_code="revision_ready_for_review", passed=True)
    except Exception as exc:
        return sat._failure("existing_chapter_revision", str(exc), "existing_chapter_revision_failed")


class HumanizeInput(BaseModel):
    context_artifact_id: str
    draft_artifact_id: str
    reason: Optional[str] = None


async def _humanize_chapter_draft(context_artifact_id: str, draft_artifact_id: str, reason=None):
    try:
        context = sat._load_artifact(context_artifact_id, "chapter_context")
        draft = sat._load_artifact(draft_artifact_id, "chapter_draft")
        rules = HUMANIZER_PATH.read_text(encoding="utf-8")
        preview = await sat._emit_content_preview_start(context)
        result = await sat._invoke_json_agent(
            "humanizer_agent.txt",
            f"======= 完整自然化规则 =======\n{rules}\n\n======= 完整作品上下文 =======\n{context.content}\n\n======= 完整正文 =======\n{draft.content}",
            content_delta_callback=(
                (lambda delta: sat._emit_content_preview_delta(preview, delta))
                if preview["enabled"] else None
            ),
        )
        content = str(result.get("content") or "")
        if not content:
            raise ValueError("自然化结果缺少完整 content")
        await sat._emit_content_preview_complete(preview, content)
        await sat._write_draft_to_existing_chapter(draft.work_id, draft.chapter_node_id, content)
        artifact = sat._create_artifact(draft.work_id, draft.chapter_node_id, "chapter_draft", content, parent_artifact_id=draft.id, version=draft.version + 1)
        public = {key: value for key, value in result.items() if key != "content"}
        public.update({"source_version": draft.version, "result_version": artifact.version, "word_count": len("".join(content.split()))})
        return sat._envelope(status="completed", agent="fiction_humanizer", artifact=artifact, inputs=[context, draft], result=public, gate_code="humanized_draft_ready", passed=True)
    except Exception as exc:
        return sat._failure("fiction_humanizer", str(exc), "humanization_failed")


async def _review_fiction_quality(context_artifact_id: str, draft_artifact_id: str, minimum_score=7, reason=None):
    try:
        context = sat._load_artifact(context_artifact_id)
        draft = sat._load_artifact(draft_artifact_id, "chapter_draft")
        result = await sat._invoke_json_agent("fiction_quality.txt", f"======= 完整上下文 =======\n{context.content}\n\n======= 完整正文 =======\n{draft.content}")
        score = int(result.get("score") or 0)
        passed = score >= minimum_score and not any(isinstance(item, dict) and item.get("severity") == "major" for item in result.get("issues") or [])
        artifact = sat._create_artifact(draft.work_id, draft.chapter_node_id, "fiction_quality_review", json.dumps(result, ensure_ascii=False), parent_artifact_id=draft.id)
        return sat._envelope(status="completed" if passed else "needs_revision", agent="fiction_quality_review", artifact=artifact, inputs=[context, draft], result=result, gate_code="fiction_quality_passed" if passed else "fiction_quality_revision_required", passed=passed)
    except Exception as exc:
        return sat._failure("fiction_quality_review", str(exc), "fiction_quality_review_failed")


class CoherenceInput(BaseModel):
    context_artifact_id: str
    reason: Optional[str] = None


async def _review_novel_coherence(context_artifact_id: str, reason=None):
    try:
        context = sat._load_artifact(context_artifact_id, "work_context")
        result = await sat._invoke_json_agent("novel_coherence.txt", context.content)
        artifact = sat._create_artifact(context.work_id, None, "novel_coherence_review", json.dumps(result, ensure_ascii=False), parent_artifact_id=context.id)
        return sat._envelope(status="completed", agent="novel_coherence_review", artifact=artifact, inputs=[context], result=result, gate_code="coherence_review_ready", passed=True)
    except Exception as exc:
        return sat._failure("novel_coherence_review", str(exc), "coherence_review_failed")


async def _extract_story_memory(context_artifact_id: str, draft_artifact_id: str, reason=None):
    try:
        context = sat._load_artifact(context_artifact_id, "chapter_context")
        draft = sat._load_artifact(draft_artifact_id, "chapter_draft")
        result = await sat._invoke_json_agent("story_memory.txt", f"======= 完整上下文 =======\n{context.content}\n\n======= 完整章节 =======\n{draft.content}")
        artifact = sat._create_artifact(draft.work_id, draft.chapter_node_id, "story_memory", json.dumps(result, ensure_ascii=False), parent_artifact_id=draft.id)
        return sat._envelope(status="completed", agent="story_memory", artifact=artifact, inputs=[context, draft], result=result, gate_code="story_memory_ready", passed=True)
    except Exception as exc:
        return sat._failure("story_memory", str(exc), "story_memory_failed")


class ResearchContextInput(BaseModel):
    research_artifact_ids: list[str] = Field(min_length=1)
    reason: Optional[str] = None


async def _resolve_research_context(research_artifact_ids: list[str], reason=None):
    db = _get_db()
    try:
        user_id = _current_context().get("user_id")
        work_id = _current_context().get("work_id")
        rows = db.query(ResearchArtifact, ResearchJob).join(ResearchJob, ResearchArtifact.job_id == ResearchJob.id).filter(ResearchJob.user_id == user_id, ResearchArtifact.id.in_(research_artifact_ids)).all()
        by_id = {artifact.id: (artifact, job) for artifact, job in rows}
        missing = [item for item in research_artifact_ids if item not in by_id]
        if missing:
            return sat._failure("research_context_resolver", f"研究成果不可用：{missing}", "research_artifact_unavailable")
        payload = {
            "source_artifact_ids": research_artifact_ids,
            "artifacts": [
                {"id": item, "title": by_id[item][0].title, "artifact_type": by_id[item][0].artifact_type, "source_filename": by_id[item][1].original_filename, "content": by_id[item][0].content}
                for item in research_artifact_ids
            ],
        }
        artifact = sat._create_artifact(work_id, None, "research_context", json.dumps(payload, ensure_ascii=False))
        return sat._envelope(status="completed", agent="research_context_resolver", artifact=artifact, result={"source_artifact_ids": research_artifact_ids, "artifact_count": len(rows)}, gate_code="research_context_ready", passed=True)
    except Exception as exc:
        return sat._failure("research_context_resolver", str(exc), "research_context_failed")
    finally:
        db.close()


class ApplyResearchInput(BaseModel):
    context_artifact_id: str
    research_context_artifact_id: str
    reason: Optional[str] = None


async def _apply_research_techniques(context_artifact_id: str, research_context_artifact_id: str, reason=None):
    try:
        context = sat._load_artifact(context_artifact_id, "work_context")
        research = sat._load_artifact(research_context_artifact_id, "research_context")
        result = await sat._invoke_json_agent("research_application.txt", f"======= 当前作品完整上下文 =======\n{context.content}\n\n======= 研究成果全文 =======\n{research.content}")
        artifact = sat._create_artifact(context.work_id, None, "research_application", json.dumps(result, ensure_ascii=False), parent_artifact_id=research.id)
        return sat._envelope(status="completed", agent="research_application", artifact=artifact, inputs=[context, research], result=result, gate_code="research_application_ready", passed=True)
    except Exception as exc:
        return sat._failure("research_application", str(exc), "research_application_failed")


load_workflow_skill = StructuredTool.from_function(coroutine=_load_workflow_skill, name="load_workflow_skill", description="按名称完整加载一个已注册的创作 Workflow Skill。", args_schema=LoadWorkflowSkillInput)
assemble_work_context = StructuredTool.from_function(coroutine=_assemble_work_context, name="assemble_work_context", description="完整装配作品节点、用户要求和目标范围，保存为工作流上下文产物。", args_schema=AssembleWorkContextInput)
review_artifact_quality = StructuredTool.from_function(coroutine=_review_artifact_quality, name="review_artifact_quality", description="对研究或故事记忆产物执行结构化质量审查。", args_schema=ArtifactReviewInput)
stage_existing_chapter_draft = StructuredTool.from_function(coroutine=_stage_existing_chapter_draft, name="stage_existing_chapter_draft", description="把章节上下文中的当前完整正文保存为版本化草稿产物。", args_schema=StageChapterInput)
revise_existing_chapter_draft = StructuredTool.from_function(coroutine=_revise_existing_chapter_draft, name="revise_existing_chapter_draft", description="按作者完整要求修改已有章节并生成新草稿版本。", args_schema=ExistingRevisionInput)
humanize_chapter_draft = StructuredTool.from_function(coroutine=_humanize_chapter_draft, name="humanize_chapter_draft", description="完整加载自然化规则，生成保持事实与标记的新草稿版本。", args_schema=HumanizeInput)
review_fiction_quality = StructuredTool.from_function(coroutine=_review_fiction_quality, name="review_fiction_quality", description="综合评估章节逻辑、人物、节奏、文风、对白和阅读体验。", args_schema=sat.ReviewInput)
review_novel_coherence = StructuredTool.from_function(coroutine=_review_novel_coherence, name="review_novel_coherence", description="只读审查多章或全书的一致性、人物线和伏笔状态。", args_schema=CoherenceInput)
extract_story_memory = StructuredTool.from_function(coroutine=_extract_story_memory, name="extract_story_memory", description="从完整章节提取摘要、章末状态、角色关系变化和未决线索。", args_schema=HumanizeInput)
resolve_research_context = StructuredTool.from_function(coroutine=_resolve_research_context, name="resolve_research_context", description="按研究成果 ID 读取全文并保存为可追踪研究上下文产物。", args_schema=ResearchContextInput)
apply_research_techniques = StructuredTool.from_function(coroutine=_apply_research_techniques, name="apply_research_techniques", description="把研究成果全文适配为当前作品可执行的技法产物。", args_schema=ApplyResearchInput)


workflow_agent_tools = [
    load_workflow_skill, assemble_work_context, review_artifact_quality,
    stage_existing_chapter_draft,
    revise_existing_chapter_draft, humanize_chapter_draft,
    review_fiction_quality, review_novel_coherence, extract_story_memory,
    resolve_research_context, apply_research_techniques,
]


DIRECT_SPECIALTIES = {
    "architecture": ("premise_architect.txt", {"outline", "volume", "plot", "chapter", "character", "worldbuilding", "note"}),
    "worldbuilding": ("worldbuilding.txt", {"worldbuilding"}),
    "characters": ("character_design.txt", {"character"}),
    "outline": ("outline_plan.txt", {"outline", "volume"}),
    "structure": ("story_structure.txt", {"volume", "plot"}),
    "chapters": ("chapter_plan.txt", {"chapter"}),
}


class DevelopExistingNodesInput(BaseModel):
    specialty: str = Field(description="专职方向：architecture、worldbuilding、characters、outline、structure、chapters")
    node_ids: list[str] = Field(min_length=1, description="已在当前作品画布创建的真实节点 UUID")
    user_instruction: str = Field(description="用户本轮完整要求")
    reason: Optional[str] = None


async def _develop_existing_nodes(specialty: str, node_ids: list[str], user_instruction: str, reason=None) -> str:
    from services.agents.tools import node_tools

    if specialty not in DIRECT_SPECIALTIES:
        return sat._failure("node_content_specialist", f"未知专职方向：{specialty}", "unknown_specialty")
    if len(node_ids) != len(set(node_ids)):
        return sat._failure("node_content_specialist", "node_ids 不能重复", "duplicate_node_id")
    work_id = _current_context().get("work_id")
    if not work_id:
        return sat._failure("node_content_specialist", "未指定作品ID", "work_not_bound")
    prompt_name, allowed_types = DIRECT_SPECIALTIES[specialty]
    db = _get_db()
    try:
        canvas_nodes = db.query(Node).filter(Node.work_id == work_id).order_by(Node.type, Node.sort_order, Node.id).all()
        by_id = {item.id: item for item in canvas_nodes}
        if any(node_id not in by_id for node_id in node_ids):
            return sat._failure("node_content_specialist", "目标节点必须已存在于当前作品", "node_not_found")
        if any(by_id[node_id].type not in allowed_types for node_id in node_ids):
            return sat._failure("node_content_specialist", "目标节点类型与专职方向不匹配", "node_type_mismatch")
        canvas_context = [{
            "node_id": item.id, "node_type": item.type, "title": item.title,
            "content": item.content or "", "sort_order": item.sort_order,
            "extra_data": item.extra_data or {},
        } for item in canvas_nodes]
        canvas_edges = [{
            "source_id": item.source_id, "target_id": item.target_id,
            "edge_type": item.edge_type,
        } for item in db.query(Edge).filter(Edge.work_id == work_id).order_by(Edge.created_at, Edge.id).all()]
    finally:
        db.close()

    system_prompt = (
        (sat.PROMPT_ROOT / prompt_name).read_text(encoding="utf-8")
        + "\n\n本次只完善已经存在的真实节点。返回 JSON 对象，包含 nodes 数组；"
        "每项包含 node_id 和完整 content，可包含 title、chapter_elements、characters、storylines。"
        "node_id 使用输入中的真实 UUID。characters 中的 id 使用当前作品已有角色节点的真实 UUID。"
        "数组字段输出 JSON 数组。"
    )
    try:
        payload = await sat._invoke_json_agent(
            prompt_name,
            "======= 用户完整要求 =======\n" + user_instruction
            + "\n\n======= 本轮要完善的真实节点 ID =======\n"
            + json.dumps(node_ids, ensure_ascii=False)
            + "\n\n======= 当前画布全部节点 =======\n"
            + json.dumps(canvas_context, ensure_ascii=False)
            + "\n\n======= 当前画布全部连线 =======\n"
            + json.dumps(canvas_edges, ensure_ascii=False),
            system_prompt=system_prompt,
        )
        rows = payload.get("nodes")
        if not isinstance(rows, list) or {row.get("node_id") for row in rows if isinstance(row, dict)} != set(node_ids) or len(rows) != len(node_ids):
            raise ValueError("专职 Agent 返回的节点 ID 必须与本轮目标真实节点完全一致")
        for row in rows:
            if not isinstance(row.get("content"), str):
                raise ValueError("节点 content 必须是完整字符串")
            if "title" in row and not isinstance(row["title"], str):
                raise ValueError("节点 title 必须是字符串")
            for field in ("chapter_elements", "characters", "storylines"):
                if field in row and not isinstance(row[field], list):
                    raise ValueError(f"{field} 必须是数组")
        db = _get_db()
        try:
            targets = {item.id: item for item in db.query(Node).filter(Node.work_id == work_id, Node.id.in_(node_ids)).all()}
            if set(targets) != set(node_ids):
                raise ValueError("目标节点已不存在")
            for row in rows:
                node = targets[row["node_id"]]
                if "title" in row:
                    node.title = row["title"]
                chapter_elements = storylines = characters = None
                if "chapter_elements" in row:
                    if node.type != "chapter":
                        raise ValueError("chapter_elements 只能写入章节节点")
                    chapter_elements, error = node_tools._normalize_chapter_elements(row["chapter_elements"])
                    if error:
                        raise ValueError(error)
                if "characters" in row:
                    if node.type != "chapter":
                        raise ValueError("characters 只能写入章节节点")
                    characters, error = node_tools._normalize_chapter_characters(row["characters"], db, work_id)
                    if error:
                        raise ValueError(error)
                if "storylines" in row:
                    if node.type != "character":
                        raise ValueError("storylines 只能写入角色节点")
                    storylines, error = node_tools._normalize_storylines(row["storylines"])
                    if error:
                        raise ValueError(error)
                node.extra_data = node_tools._merge_extra_data_fields(
                    node.extra_data, chapter_elements=chapter_elements,
                    characters=characters, storylines=storylines,
                )
                write_node_content(db, node, row["content"])
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        emit = sat._get_emit()
        if emit:
            await emit("nodes_updated", {"action": "direct_node_write", "node_ids": node_ids})
        return sat._envelope(
            status="completed", agent="node_content_specialist",
            result={"nodes": [{"id": row["node_id"], "title": row.get("title")} for row in rows]},
            gate_code="nodes_written", passed=True,
        )
    except Exception as exc:
        return sat._failure("node_content_specialist", str(exc), "node_write_failed")


develop_existing_nodes = StructuredTool.from_function(
    coroutine=_develop_existing_nodes, name="develop_existing_nodes",
    description="调用专职 Agent 完善当前作品中已创建的真实节点，并直接写入节点；仅返回节点 ID 和简要结果。",
    args_schema=DevelopExistingNodesInput,
)
workflow_agent_tools.append(develop_existing_nodes)
