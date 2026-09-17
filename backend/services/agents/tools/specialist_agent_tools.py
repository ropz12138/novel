"""供 Supervisor 按写章 Skill 调用的专职 Agent 工具。"""
from __future__ import annotations

import json
import hashlib
import inspect
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from models.node import Node
from models.edge import Edge
from models.work import CanvasWork
from models.workflow import WorkflowArtifact
from node_types import resolve_scope, validate_edge_endpoints
from services.edge_layout_service import build_edge_layout
from services.edge_relation import validate_hierarchy_structure


AGENT_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = AGENT_ROOT / "skills" / "write-chapter" / "SKILL.md"
PROMPT_ROOT = AGENT_ROOT / "prompts" / "specialists"
JSON_OUTPUT_RULES_PATH = AGENT_ROOT / "prompts" / "json_output_rules.txt"


def _get_chapter_review_policy():
    from services.agents.chapter_review_policy import get_chapter_review_policy

    return get_chapter_review_policy()


def _get_db():
    from database import SessionLocal

    return SessionLocal()


def _get_current_work_id() -> str | None:
    try:
        from services.agents.supervisor import get_context

        return get_context().get("work_id")
    except Exception:
        return None


def _get_emit():
    try:
        from services.agents.supervisor import get_context

        return get_context().get("emit")
    except Exception:
        return None


async def _write_draft_to_existing_chapter(work_id: str | None, chapter_node_id: str | None, content: str) -> None:
    if not chapter_node_id:
        return
    from services.node_content_write_service import write_node_content

    db = _get_db()
    try:
        chapter = db.query(Node).filter(
            Node.id == chapter_node_id,
            Node.work_id == work_id,
            Node.type == "chapter",
        ).first()
        if chapter is None:
            raise ValueError("草稿对应的真实章节节点不存在")
        write_node_content(db, chapter, content)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    emit = _get_emit()
    if emit:
        await emit("nodes_updated", {
            "action": "chapter_draft_write", "chapter_node_id": chapter_node_id,
            "content_changed": True,
        })


def _record_workflow_gate(*, passed: bool, code: str, status: str) -> None:
    try:
        from services.agents.supervisor import get_context

        get_context()["workflow_gate"] = {
            "passed": passed,
            "code": code,
            "status": status,
        }
    except Exception:
        return


def _create_artifact(
    work_id: str | None,
    chapter_node_id: str | None,
    artifact_type: str,
    content: str,
    *,
    run_id: str | None = None,
    parent_artifact_id: str | None = None,
    version: int = 1,
) -> WorkflowArtifact:
    db = _get_db()
    try:
        artifact = WorkflowArtifact(
            run_id=run_id,
            work_id=work_id,
            chapter_node_id=chapter_node_id,
            parent_artifact_id=parent_artifact_id,
            artifact_type=artifact_type,
            version=version,
            content=content,
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        db.expunge(artifact)
        return artifact
    finally:
        db.close()


def _load_artifact(artifact_id: str, expected_type: str | None = None) -> WorkflowArtifact:
    db = _get_db()
    try:
        artifact = db.query(WorkflowArtifact).filter(WorkflowArtifact.id == artifact_id).first()
        if artifact is None:
            raise ValueError(f"工作流产物不存在：{artifact_id}")
        if expected_type and artifact.artifact_type != expected_type:
            raise ValueError(
                f"工作流产物类型不匹配：需要 {expected_type}，实际为 {artifact.artifact_type}"
            )
        db.expunge(artifact)
        return artifact
    finally:
        db.close()


def _artifact_ref(artifact: WorkflowArtifact) -> dict:
    return {
        "id": artifact.id,
        "type": artifact.artifact_type,
        "version": artifact.version,
    }


def _content_sha256(content: str | None) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _input_ref(artifact: WorkflowArtifact) -> dict:
    return {"artifact_id": artifact.id, "version": artifact.version}


def _envelope(
    *,
    status: str,
    agent: str,
    result: dict,
    gate_code: str,
    passed: bool,
    artifact: WorkflowArtifact | None = None,
    inputs: list[WorkflowArtifact] | None = None,
    user_decision: dict | None = None,
) -> str:
    _record_workflow_gate(passed=passed, code=gate_code, status=status)
    return json.dumps(
        {
            "success": True,
            "status": status,
            "agent": agent,
            "artifact": _artifact_ref(artifact) if artifact else None,
            "inputs": [_input_ref(item) for item in inputs or []],
            "result": result,
            "gate": {"passed": passed, "code": gate_code},
            "user_decision": user_decision,
            "error": None,
        },
        ensure_ascii=False,
    )


def _failure(agent: str, message: str, code: str = "agent_execution_failed") -> str:
    _record_workflow_gate(passed=False, code=code, status="failed")
    return json.dumps(
        {
            "success": False,
            "status": "failed",
            "agent": agent,
            "artifact": None,
            "inputs": [],
            "result": {},
            "gate": {"passed": False, "code": code},
            "user_decision": None,
            "error": {"message": message},
        },
        ensure_ascii=False,
    )


def _strip_fences(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


def _response_text(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return str(content)


def _load_json_output_rules() -> str:
    return JSON_OUTPUT_RULES_PATH.read_text(encoding="utf-8")


class _JsonContentStreamDecoder:
    """从流式 JSON 中增量解码顶层 content 字符串。"""

    def __init__(self) -> None:
        self.buffer = ""
        self.position: int | None = None
        self.finished = False

    def feed(self, chunk: str) -> str:
        if self.finished or not chunk:
            return ""
        self.buffer += chunk
        if self.position is None:
            match = re.search(r'"content"\s*:\s*"', self.buffer)
            if match is None:
                return ""
            self.position = match.end()

        output = []
        while self.position < len(self.buffer):
            char = self.buffer[self.position]
            if char == '"':
                self.position += 1
                self.finished = True
                break
            if char != "\\":
                output.append(char)
                self.position += 1
                continue
            if self.position + 1 >= len(self.buffer):
                break
            escaped = self.buffer[self.position + 1]
            if escaped == "u":
                if self.position + 6 > len(self.buffer):
                    break
                code = self.buffer[self.position + 2:self.position + 6]
                try:
                    output.append(chr(int(code, 16)))
                except ValueError:
                    output.append("\\u" + code)
                self.position += 6
                continue
            output.append({
                '"': '"', "\\": "\\", "/": "/", "b": "\b",
                "f": "\f", "n": "\n", "r": "\r", "t": "\t",
            }.get(escaped, escaped))
            self.position += 2
        return "".join(output)


async def _invoke_json_agent(
    prompt_name: str,
    user_content: str,
    *,
    system_prompt: str | None = None,
    content_delta_callback=None,
) -> dict:
    from services.agents import llm as llm_module

    prompt = system_prompt or (PROMPT_ROOT / prompt_name).read_text(encoding="utf-8")
    prompt = f"{prompt}\n\n{_load_json_output_rules()}"
    llm = llm_module.get_llm(temperature=0.5, streaming=False, **llm_module.context_model_pref_kwargs())
    messages = [SystemMessage(content=prompt), HumanMessage(content=user_content)]
    if content_delta_callback is None:
        response = await llm.ainvoke(messages)
    else:
        decoder = _JsonContentStreamDecoder()
        aggregated = None
        async for chunk in llm.astream(messages):
            aggregated = chunk if aggregated is None else aggregated + chunk
            delta = decoder.feed(_response_text(chunk))
            if delta:
                callback_result = content_delta_callback(delta)
                if inspect.isawaitable(callback_result):
                    await callback_result
        if aggregated is None:
            raise RuntimeError("LLM 未返回任何响应")
        response = aggregated
    data = json.loads(_strip_fences(_response_text(response)))
    if not isinstance(data, dict):
        raise ValueError("专职 Agent 返回结果不是 JSON 对象")
    return data


async def _emit_content_preview_start(context: WorkflowArtifact) -> dict:
    context_data = _json_content(context)
    target = context_data.get("target_chapter") or {}
    state = {
        "node_id": context.chapter_node_id,
        "node_type": "chapter",
        "title": str(target.get("title") or ""),
        "original_content": str(target.get("content") or ""),
        "current_content": "",
        "enabled": False,
        "pending_chunk": "",
    }
    emit = _get_emit()
    if emit and state["node_id"]:
        state["enabled"] = True
        await emit("node_content_diff_preview", {
            "phase": "start",
            "node_id": state["node_id"],
            "node_type": state["node_type"],
            "title": state["title"],
            "original_content": state["original_content"],
        })
    return state


async def _emit_content_preview_delta(state: dict, delta: str) -> None:
    state["current_content"] += delta
    state["pending_chunk"] += delta
    if len(state["pending_chunk"]) < 64 and "\n" not in state["pending_chunk"]:
        return
    emit = _get_emit()
    if emit and state.get("node_id"):
        await emit("node_content_diff_preview", {
            "phase": "delta",
            "node_id": state["node_id"],
            "chunk": state["pending_chunk"],
        })
        state["pending_chunk"] = ""


async def _emit_content_preview_complete(state: dict, content: str) -> None:
    emit = _get_emit()
    if emit and state.get("node_id"):
        if state.get("pending_chunk"):
            await emit("node_content_diff_preview", {
                "phase": "delta",
                "node_id": state["node_id"],
                "chunk": state["pending_chunk"],
            })
            state["pending_chunk"] = ""
        await emit("node_content_diff_preview", {
            "phase": "complete",
            "node_id": state["node_id"],
            "current_content": content,
        })


def _json_content(artifact: WorkflowArtifact) -> dict:
    data = json.loads(artifact.content)
    if not isinstance(data, dict):
        raise ValueError(f"{artifact.artifact_type} 产物内容不是对象")
    return data


def _ancestor_artifact(artifact: WorkflowArtifact, artifact_type: str) -> WorkflowArtifact | None:
    current = artifact
    visited = set()
    while current and current.id not in visited:
        visited.add(current.id)
        if current.artifact_type == artifact_type:
            return current
        if not current.parent_artifact_id:
            return None
        current = _load_artifact(current.parent_artifact_id)
    return None


def _draft_length_result(draft: WorkflowArtifact) -> dict | None:
    context = _ancestor_artifact(draft, "chapter_context")
    if context is None:
        return None
    target_words = int(_json_content(context).get("target_words") or 0)
    if not target_words:
        return None
    word_count = len("".join(draft.content.split()))
    minimum_words = max(1, target_words * 85 // 100)
    maximum_words = target_words * 115 // 100
    return {
        "word_count": word_count,
        "minimum_words": minimum_words,
        "target_words": target_words,
        "maximum_words": maximum_words,
        "missing_words": max(0, minimum_words - word_count),
        "excess_words": max(0, word_count - maximum_words),
        "passed": minimum_words <= word_count <= maximum_words,
    }


class LoadSkillInput(BaseModel):
    reason: Optional[str] = Field(default=None, description="加载写章工作流技能的原因")


async def _load_write_chapter_skill(reason=None) -> str:
    try:
        content = SKILL_PATH.read_text(encoding="utf-8")
        policy = _get_chapter_review_policy()
        if policy:
            content += f"\n\n本次执行的章节评审强度：{policy.intensity}。按本技能的对应档位执行。"
        return _envelope(
            status="completed",
            agent="workflow_skill_loader",
            result={"skill_name": "write-chapter", "skill_content": content},
            gate_code="workflow_skill_loaded",
            passed=True,
        )
    except Exception as exc:
        return _failure("workflow_skill_loader", str(exc), "workflow_skill_load_failed")


class AssembleContextInput(BaseModel):
    chapter_node_id: Optional[str] = Field(
        default=None,
        description="已有目标章节节点 ID。续写或修改已有章节时必填。与 parent_node_id、chapter_title、sort_order 互斥。",
    )
    parent_node_id: Optional[str] = Field(
        default=None,
        description="尚无章节节点时必填：父情节节点 ID。父节点必须是 plot。与 chapter_node_id 互斥。",
    )
    chapter_title: Optional[str] = Field(
        default=None,
        description="尚无章节节点时必填：新章节标题。",
    )
    sort_order: Optional[int] = Field(
        default=None,
        description="尚无章节节点时必填：同级顺序整数。",
    )
    user_instruction: str = Field(default="", description="用户本轮完整写作要求")
    target_words: int = Field(default=3000, gt=0, description="目标正文篇幅")
    reason: Optional[str] = Field(default=None, description="调用原因")


def _filled_text(value: str | None) -> str:
    return (value or "").strip()


def _create_chapter_under_plot(db, work_id: str, parent_node_id: str, chapter_title: str, sort_order: int):
    parent = db.query(Node).filter(Node.id == parent_node_id, Node.work_id == work_id).first()
    if parent is None:
        return None, _failure("context_assembler", "父节点不存在", "parent_node_not_found")
    if parent.type != "plot":
        return None, _failure(
            "context_assembler",
            f"新建章节的父节点必须是 plot，实际为 {parent.type}",
            "invalid_parent_type",
        )
    chapter = Node(
        id=str(uuid.uuid4()),
        work_id=work_id,
        type="chapter",
        title=chapter_title,
        content="",
        layer=0,
        sort_order=sort_order,
        scope=resolve_scope("chapter", None),
        extra_data={},
    )
    db.add(chapter)
    db.flush()
    endpoint_err = validate_edge_endpoints(parent.type, chapter.type, parent.scope, chapter.scope)
    if endpoint_err:
        db.rollback()
        return None, _failure("context_assembler", endpoint_err, "invalid_parent_type")
    structure_err = validate_hierarchy_structure(db, work_id, parent, chapter)
    if structure_err:
        db.rollback()
        return None, _failure("context_assembler", structure_err, "invalid_parent_type")
    edge = Edge(
        id=str(uuid.uuid4()),
        work_id=work_id,
        source_id=parent.id,
        target_id=chapter.id,
        edge_type="contains",
        label="",
        extra_data=build_edge_layout(parent, chapter),
    )
    db.add(edge)
    db.commit()
    db.refresh(chapter)
    return chapter, None


async def _assemble_chapter_context(
    chapter_node_id: str | None = None,
    parent_node_id: str | None = None,
    chapter_title: str | None = None,
    sort_order: int | None = None,
    user_instruction: str = "",
    target_words: int = 3000,
    reason: str | None = None,
) -> str:
    db = _get_db()
    try:
        existing_id = _filled_text(chapter_node_id)
        create_parent_id = _filled_text(parent_node_id)
        create_title = _filled_text(chapter_title)
        has_any_create = bool(create_parent_id or create_title or sort_order is not None)
        has_all_create = bool(create_parent_id and create_title and sort_order is not None)
        if existing_id and has_any_create:
            return _failure(
                "context_assembler",
                "chapter_node_id 与新建参数互斥，只能使用其中一组",
                "chapter_context_mode_conflict",
            )
        if not existing_id and not has_any_create:
            return _failure(
                "context_assembler",
                "必须提供 chapter_node_id，或同时提供 parent_node_id、chapter_title、sort_order",
                "chapter_context_target_required",
            )
        if not existing_id and not has_all_create:
            return _failure(
                "context_assembler",
                "新建章节必须同时提供 parent_node_id、chapter_title、sort_order",
                "chapter_create_params_incomplete",
            )
        work_id = _get_current_work_id()
        chapter_created = False
        parent_id = None
        if existing_id:
            chapter = db.query(Node).filter(Node.id == existing_id, Node.type == "chapter").first()
            if chapter is None or (work_id and chapter.work_id != work_id):
                return _failure("context_assembler", "目标章节不存在", "chapter_not_found")
        else:
            if not work_id:
                return _failure("context_assembler", "未指定作品ID", "work_id_required")
            chapter, error = _create_chapter_under_plot(
                db, work_id, create_parent_id, create_title, sort_order
            )
            if error:
                return error
            chapter_created = True
            parent_id = create_parent_id
        work_id = chapter.work_id
        work = db.query(CanvasWork).filter(CanvasWork.id == work_id).first()
        nodes = db.query(Node).filter(Node.work_id == work_id).order_by(Node.sort_order, Node.id).all()
        chapters = [item for item in nodes if item.type == "chapter"]
        chapter_index = next(index for index, item in enumerate(chapters) if item.id == chapter.id)
        previous = chapters[chapter_index - 1] if chapter_index > 0 else None
        globals_ = [item for item in nodes if item.type in ("note", "worldbuilding")]
        characters = [item for item in nodes if item.type == "character"]
        structure = [item for item in nodes if item.type in ("outline", "volume", "plot")]
        previous_chapters = chapters[:chapter_index]
        context_data = {
            "work": {"id": work_id, "title": work.title if work else ""},
            "target_chapter": {
                "id": chapter.id,
                "title": chapter.title,
                "sort_order": chapter.sort_order,
                "content": chapter.content or "",
                "chapter_elements": (chapter.extra_data or {}).get("chapter_elements", []),
                "characters": (chapter.extra_data or {}).get("characters", []),
            },
            "target_words": target_words,
            "source_content_sha256": _content_sha256(chapter.content),
            "user_instruction": user_instruction,
            "story_structure": [
                {"id": item.id, "type": item.type, "title": item.title, "content": item.content or ""}
                for item in structure
            ],
            "global_context": [
                {"id": item.id, "type": item.type, "title": item.title, "content": item.content or ""}
                for item in globals_
            ],
            "characters": [
                {
                    "id": item.id,
                    "name": item.title,
                    "scope": item.scope,
                    "content": item.content or "",
                    "storylines": (item.extra_data or {}).get("storylines", []),
                }
                for item in characters
            ],
            "previous_chapters": [
                {"id": item.id, "title": item.title, "content": item.content or ""}
                for item in previous_chapters
            ],
            "previous_chapter": (
                {"id": previous.id, "title": previous.title, "content": previous.content or ""}
                if previous else None
            ),
        }
        artifact = _create_artifact(
            work_id,
            chapter.id,
            "chapter_context",
            json.dumps(context_data, ensure_ascii=False),
        )
        result = {
            "work_id": work_id,
            "chapter_node_id": chapter.id,
            "chapter_title": chapter.title,
            "chapter_created": chapter_created,
            "target_words": target_words,
            "source_content_sha256": _content_sha256(chapter.content),
            "previous_chapter": (
                {"node_id": previous.id, "title": previous.title} if previous else None
            ),
            "context_inventory": {
                "structure_count": len(structure),
                "global_context_count": len(globals_),
                "character_count": len(characters),
                "previous_chapter_count": len(previous_chapters),
            },
            "missing_requirements": [],
        }
        if parent_id:
            result["parent_node_id"] = parent_id
        return _envelope(
            status="completed",
            agent="context_assembler",
            artifact=artifact,
            result=result,
            gate_code="context_ready",
            passed=True,
        )
    except Exception as exc:
        db.rollback()
        return _failure("context_assembler", str(exc), "context_assembly_failed")
    finally:
        db.close()


class ArtifactInput(BaseModel):
    context_artifact_id: str = Field(description="完整章节上下文产物 ID")
    reason: Optional[str] = Field(default=None, description="调用原因")


async def _plan_chapter_scenes(context_artifact_id: str, reason=None) -> str:
    try:
        context = _load_artifact(context_artifact_id, "chapter_context")
        result = await _invoke_json_agent("scene_plan.txt", context.content)
        scenes = result.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            raise ValueError("场景规划缺少 scenes")
        orders = [item.get("order") for item in scenes if isinstance(item, dict)]
        if orders != list(range(1, len(scenes) + 1)):
            raise ValueError("场景序号需要从 1 连续递增")
        artifact = _create_artifact(
            context.work_id,
            context.chapter_node_id,
            "scene_plan",
            json.dumps(result, ensure_ascii=False),
            parent_artifact_id=context.id,
        )
        public_result = {
            "chapter_goal": result.get("chapter_goal", ""),
            "opening_carryover": result.get("opening_carryover", ""),
            "emotional_progression": result.get("emotional_progression", ""),
            "scene_count": len(scenes),
            "estimated_words": sum(int(item.get("approximate_words") or 0) for item in scenes),
            "scenes": [
                {
                    "order": item.get("order"),
                    "title": item.get("title", ""),
                    "purpose": item.get("purpose", ""),
                    "characters": item.get("characters", []),
                    "estimated_words": item.get("approximate_words", 0),
                    "dialogue_purpose": "；".join(
                        str(beat.get("dialogue_purpose", ""))
                        for beat in item.get("beats", [])
                        if isinstance(beat, dict) and beat.get("dialogue_purpose")
                    ),
                    "emotional_shift": item.get("emotional_shift", ""),
                }
                for item in scenes
            ],
            "ending_hook": result.get("ending_hook", ""),
        }
        return _envelope(
            status="completed",
            agent="scene_plan",
            artifact=artifact,
            inputs=[context],
            result=public_result,
            gate_code="scene_plan_ready",
            passed=True,
        )
    except Exception as exc:
        return _failure("scene_plan", str(exc), "scene_plan_failed")


class WriteDraftInput(BaseModel):
    context_artifact_id: str
    scene_plan_artifact_id: str
    reason: Optional[str] = None


class PrepareChapterInput(BaseModel):
    chapter_node_id: str
    scene_plan_artifact_id: str
    character_node_ids: list[str] = Field(default_factory=list)
    reason: Optional[str] = None


async def _prepare_chapter_from_scene_plan(
    chapter_node_id: str,
    scene_plan_artifact_id: str,
    character_node_ids: list[str] | None = None,
    reason: str | None = None,
) -> str:
    db = _get_db()
    try:
        plan = _load_artifact(scene_plan_artifact_id, "scene_plan")
        chapter = db.query(Node).filter(
            Node.id == chapter_node_id,
            Node.type == "chapter",
        ).first()
        if chapter is None:
            return _failure("chapter_structure", "目标章节不存在", "chapter_not_found")
        if plan.chapter_node_id and plan.chapter_node_id != chapter.id:
            return _failure(
                "chapter_structure",
                "场景计划不属于目标章节",
                "scene_plan_chapter_mismatch",
            )
        plan_data = _json_content(plan)
        scenes = plan_data.get("scenes") or []
        if not isinstance(scenes, list) or not scenes:
            return _failure("chapter_structure", "场景计划缺少 scenes", "scene_plan_scenes_required")
        chapter_elements = []
        for index, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                return _failure(
                    "chapter_structure",
                    f"scenes[{index}] 必须是对象",
                    "scene_plan_structure_invalid",
                )
            title = str(scene.get("title") or "").strip()
            content = str(scene.get("purpose") or "").strip()
            if not title and not content:
                return _failure(
                    "chapter_structure",
                    f"scenes[{index}] 缺少 title 和 purpose",
                    "scene_plan_structure_invalid",
                )
            chapter_elements.append({"title": title, "content": content})

        ids = list(dict.fromkeys(character_node_ids or []))
        characters = []
        if ids:
            rows = db.query(Node).filter(Node.id.in_(ids), Node.work_id == chapter.work_id).all()
            by_id = {item.id: item for item in rows}
            for character_id in ids:
                character = by_id.get(character_id)
                if character is None:
                    return _failure(
                        "chapter_structure",
                        f"角色不存在：{character_id}",
                        "character_not_found",
                    )
                if character.type != "character":
                    return _failure(
                        "chapter_structure",
                        f"节点不是角色：{character_id}",
                        "character_type_required",
                    )
                characters.append({"id": character.id, "name": character.title})

        original_content_sha256 = _content_sha256(chapter.content)
        extra_data = dict(chapter.extra_data or {})
        extra_data["chapter_elements"] = chapter_elements
        extra_data["characters"] = characters
        chapter.extra_data = extra_data
        db.commit()
        db.refresh(chapter)
        content_unchanged = _content_sha256(chapter.content) == original_content_sha256
        result = _envelope(
            status="completed",
            agent="chapter_structure",
            artifact=plan,
            inputs=[plan],
            result={
                "chapter_node_id": chapter.id,
                "chapter_element_count": len(chapter_elements),
                "character_count": len(characters),
                "content_unchanged": content_unchanged,
            },
            gate_code="chapter_structure_prepared",
            passed=content_unchanged,
        )
        emit = _get_emit()
        if emit:
            await emit("nodes_updated", {
                "action": "chapter_structure_prepare",
                "chapter_node_id": chapter.id,
                "content_changed": False,
            })
        return result
    except Exception as exc:
        db.rollback()
        return _failure("chapter_structure", str(exc), "chapter_structure_prepare_failed")
    finally:
        db.close()


async def _write_chapter_draft(context_artifact_id: str, scene_plan_artifact_id: str, reason=None) -> str:
    try:
        context = _load_artifact(context_artifact_id, "chapter_context")
        plan = _load_artifact(scene_plan_artifact_id, "scene_plan")
        context_data = _json_content(context)
        target_words = int(context_data.get("target_words") or 0)
        minimum_words = max(1, target_words * 85 // 100) if target_words else 0
        maximum_words = target_words * 115 // 100 if target_words else 0
        plan_data = _json_content(plan)
        scene_budgets = "\n".join(
            f"第{scene['order']}场《{scene['title']}》：约{scene['approximate_words']}字"
            for scene in plan_data.get("scenes", [])
        )
        length_instruction = (
            f"======= 本章篇幅要求 =======\n"
            f"目标字数：{target_words}字\n"
            f"允许范围：{minimum_words}—{maximum_words}字\n"
            f"按各场预计字数分配正文篇幅，并在允许范围内完成全部场景与章末落点。\n"
            f"{scene_budgets}\n\n"
            if target_words else ""
        )
        user_content = (
            f"{length_instruction}"
            f"======= 完整作品上下文 =======\n{context.content}\n\n"
            f"======= 完整场景计划 =======\n{plan.content}"
        )
        preview = await _emit_content_preview_start(context)
        result = await _invoke_json_agent(
            "chapter_writer.txt",
            user_content,
            content_delta_callback=(
                (lambda delta: _emit_content_preview_delta(preview, delta))
                if preview["enabled"] else None
            ),
        )
        content = str(result.get("content") or "")
        if not content.strip():
            raise ValueError("正文写作结果缺少完整 content")
        await _emit_content_preview_complete(preview, content)
        await _write_draft_to_existing_chapter(context.work_id, context.chapter_node_id, content)
        artifact = _create_artifact(
            context.work_id,
            context.chapter_node_id,
            "chapter_draft",
            content,
            parent_artifact_id=plan.id,
        )
        word_count = len("".join(content.split()))
        length_passed = not target_words or minimum_words <= word_count <= maximum_words
        public_result = {
            "word_count": word_count,
            "scene_count": len(result.get("scene_coverage") or []),
            "scene_coverage": result.get("scene_coverage") or [],
            "opening_excerpt": result.get("opening_excerpt") or content[:160],
            "ending_excerpt": result.get("ending_excerpt") or content[-160:],
            "completion": result.get("completion") or {},
        }
        if target_words:
            public_result.update({
                "minimum_words": minimum_words,
                "target_words": target_words,
                "maximum_words": maximum_words,
                "missing_words": max(0, minimum_words - word_count),
                "excess_words": max(0, word_count - maximum_words),
            })
            if word_count < minimum_words:
                public_result["feedback"] = (
                    f"章节初稿共{word_count}字，目标{target_words}字，"
                    f"允许范围{minimum_words}—{maximum_words}字；"
                    f"低于下限{minimum_words - word_count}字。"
                    "请在修订时补足正文至允许范围。"
                )
            elif word_count > maximum_words:
                public_result["feedback"] = (
                    f"章节初稿共{word_count}字，目标{target_words}字，"
                    f"允许范围{minimum_words}—{maximum_words}字；"
                    f"超出上限{word_count - maximum_words}字。"
                    "请在修订时精简正文至允许范围。"
                )
            if not length_passed:
                advice_result = await _invoke_json_agent(
                    "chapter_length_advice.txt",
                    f"======= 完整作品上下文 =======\n{context.content}\n\n"
                    f"======= 完整场景计划 =======\n{plan.content}\n\n"
                    f"======= 完整章节正文 =======\n{content}\n\n"
                    f"======= 字数统计 =======\n{public_result['feedback']}",
                )
                advice = advice_result.get("advice")
                if not isinstance(advice, str) or not advice.strip():
                    raise ValueError("篇幅修订建议缺少 advice")
                public_result["revision_advice"] = advice.strip()
        return _envelope(
            status="completed" if length_passed else "needs_revision",
            agent="chapter_writer",
            artifact=artifact,
            inputs=[context, plan],
            result=public_result,
            gate_code="draft_ready" if length_passed else "draft_length_revision_required",
            passed=length_passed,
        )
    except Exception as exc:
        return _failure("chapter_writer", str(exc), "chapter_draft_failed")


class ReviewInput(BaseModel):
    context_artifact_id: str
    draft_artifact_id: str
    minimum_score: int = Field(default=7, ge=1, le=10)
    reason: Optional[str] = None


async def _run_review(kind: str, prompt: str, context_id: str, draft_id: str, minimum_score: int) -> str:
    try:
        policy = _get_chapter_review_policy()
        if policy and policy.intensity == "low":
            return _envelope(
                status="completed", agent=f"{kind}_review",
                result={"reason": "当前章节评审强度为低"},
                gate_code=f"{kind}_skipped_by_intensity", passed=True,
            )
        context = _load_artifact(context_id, "chapter_context")
        draft = _load_artifact(draft_id, "chapter_draft")
        if policy and not policy.try_reserve(kind, draft.chapter_node_id or draft.id):
            return _envelope(
                status="completed", agent=f"{kind}_review",
                result={"reason": "当前章节已完成该项评审"},
                gate_code=f"{kind}_review_limit_reached", passed=True,
            )
        user_content = f"======= 完整作品上下文 =======\n{context.content}\n\n======= 完整章节草稿 =======\n{draft.content}"
        result = await _invoke_json_agent(prompt, user_content)
        score = int(result.get("score") or 0)
        issues = result.get("issues") or []
        passed = score >= minimum_score and not any(
            isinstance(item, dict) and item.get("severity") in {"major", "moderate", "medium"}
            for item in issues
        )
        if policy:
            policy.record_result(kind, draft.chapter_node_id or draft.id, passed=passed)
        artifact = _create_artifact(
            draft.work_id,
            draft.chapter_node_id,
            f"{kind}_review",
            json.dumps(result, ensure_ascii=False),
            parent_artifact_id=draft.id,
        )
        return _envelope(
            status="completed" if passed else "needs_revision",
            agent=f"{kind}_review",
            artifact=artifact,
            inputs=[context, draft],
            result=result,
            gate_code=f"{kind}_passed" if passed else f"{kind}_revision_required",
            passed=passed,
        )
    except Exception as exc:
        return _failure(f"{kind}_review", str(exc), f"{kind}_review_failed")


async def _review_chapter_continuity(context_artifact_id: str, draft_artifact_id: str, minimum_score=7, reason=None) -> str:
    return await _run_review("continuity", "continuity_review.txt", context_artifact_id, draft_artifact_id, minimum_score)


async def _review_chapter_dialogue(context_artifact_id: str, draft_artifact_id: str, minimum_score=7, reason=None) -> str:
    return await _run_review("dialogue", "dialogue_review.txt", context_artifact_id, draft_artifact_id, minimum_score)


class ReviseDraftInput(BaseModel):
    draft_artifact_id: str
    review_artifact_ids: list[str] = Field(min_length=1)
    reason: Optional[str] = None


async def _revise_chapter_draft(draft_artifact_id: str, review_artifact_ids: list[str], reason=None) -> str:
    try:
        draft = _load_artifact(draft_artifact_id, "chapter_draft")
        reviews = [_load_artifact(item) for item in review_artifact_ids]
        invalid = [item.artifact_type for item in reviews if not item.artifact_type.endswith("_review")]
        if invalid:
            raise ValueError(f"修订输入包含非审查产物：{', '.join(invalid)}")
        review_text = "\n\n".join(
            f"======= 审查产物 {item.id} =======\n{item.content}" for item in reviews
        )
        context = _ancestor_artifact(draft, "chapter_context")
        preview = await _emit_content_preview_start(context) if context else None
        result = await _invoke_json_agent(
            "revision.txt",
            f"======= 完整章节草稿 =======\n{draft.content}\n\n{review_text}",
            content_delta_callback=(
                (lambda delta: _emit_content_preview_delta(preview, delta))
                if preview and preview["enabled"] else None
            ),
        )
        content = str(result.get("content") or "")
        if not content.strip():
            raise ValueError("修订结果缺少完整 content")
        if preview:
            await _emit_content_preview_complete(preview, content)
        await _write_draft_to_existing_chapter(draft.work_id, draft.chapter_node_id, content)
        artifact = _create_artifact(
            draft.work_id,
            draft.chapter_node_id,
            "chapter_draft",
            content,
            parent_artifact_id=draft.id,
            version=draft.version + 1,
        )
        public_result = {
            "source_version": draft.version,
            "result_version": artifact.version,
            "word_count_before": len("".join(draft.content.split())),
            "word_count_after": len("".join(content.split())),
            "resolved_issue_ids": result.get("resolved_issue_ids") or [],
            "changed_scopes": result.get("changed_scopes") or [],
            "preservation_check": result.get("preservation_check") or {},
            "opening_excerpt": content[:160],
            "ending_excerpt": content[-160:],
        }
        return _envelope(
            status="completed",
            agent="chapter_revision",
            artifact=artifact,
            inputs=[draft, *reviews],
            result=public_result,
            gate_code="revision_ready_for_recheck",
            passed=True,
        )
    except Exception as exc:
        return _failure("chapter_revision", str(exc), "chapter_revision_failed")


class RevisionDecisionInput(BaseModel):
    context_artifact_id: str
    scene_plan_artifact_id: str
    draft_artifact_id: str
    feedback: str
    review_artifact_ids: list[str] = Field(default_factory=list)
    reason: Optional[str] = None


async def _decide_chapter_revision(
    context_artifact_id: str,
    scene_plan_artifact_id: str,
    draft_artifact_id: str,
    feedback: str,
    review_artifact_ids: list[str] | None = None,
    reason=None,
) -> str:
    try:
        context = _load_artifact(context_artifact_id, "chapter_context")
        plan = _load_artifact(scene_plan_artifact_id, "scene_plan")
        draft = _load_artifact(draft_artifact_id, "chapter_draft")
        reviews = [_load_artifact(item) for item in review_artifact_ids or []]
        if not feedback.strip() and not reviews:
            raise ValueError("修订反馈不能为空")
        full_feedback = feedback + "".join(
            f"\n\n======= 审查产物 {item.id} =======\n{item.content}" for item in reviews
        )
        result = await _invoke_json_agent(
            "chapter_revision_decision.txt",
            f"======= 完整作品上下文 =======\n{context.content}\n\n"
            f"======= 当前场景计划 =======\n{plan.content}\n\n"
            f"======= 当前章节草稿 =======\n{draft.content}\n\n"
            f"======= 本轮完整反馈 =======\n{full_feedback}",
        )
        strategy = result.get("strategy")
        if strategy not in {"replan", "rewrite", "local_edit"}:
            raise ValueError(f"修订策略无效：{strategy}")
        if not str(result.get("reason") or "").strip() or not str(result.get("instructions") or "").strip():
            raise ValueError("修订决策缺少原因或执行要求")
        decision = {
            "strategy": strategy,
            "reason": result["reason"],
            "instructions": result["instructions"],
            "feedback": full_feedback,
            "scene_plan_artifact_id": plan.id,
        }
        artifact = _create_artifact(
            draft.work_id, draft.chapter_node_id, "chapter_revision_decision",
            json.dumps(decision, ensure_ascii=False), parent_artifact_id=draft.id,
        )
        return _envelope(
            status="completed", agent="chapter_revision_decider", artifact=artifact,
            inputs=[context, plan, draft, *reviews],
            result={key: decision[key] for key in ("strategy", "reason", "instructions")},
            gate_code="revision_strategy_selected", passed=True,
        )
    except Exception as exc:
        return _failure("chapter_revision_decider", str(exc), "revision_decision_failed")


class ExecuteRevisionInput(BaseModel):
    context_artifact_id: str
    draft_artifact_id: str
    decision_artifact_id: str
    reason: Optional[str] = None


def _revision_inputs(context_artifact_id: str, draft_artifact_id: str, decision_artifact_id: str, expected_strategy: str):
    context = _load_artifact(context_artifact_id, "chapter_context")
    draft = _load_artifact(draft_artifact_id, "chapter_draft")
    decision = _load_artifact(decision_artifact_id, "chapter_revision_decision")
    data = json.loads(decision.content)
    if data.get("strategy") != expected_strategy or decision.parent_artifact_id != draft.id:
        raise ValueError("修订决策与当前草稿或执行策略不匹配")
    return context, draft, decision, data


async def _edit_chapter_draft_locally(context_artifact_id: str, draft_artifact_id: str, decision_artifact_id: str, reason=None) -> str:
    try:
        context, draft, decision, data = _revision_inputs(
            context_artifact_id, draft_artifact_id, decision_artifact_id, "local_edit"
        )
        policy = _get_chapter_review_policy()
        if policy and not policy.try_reserve_revision(draft.chapter_node_id or draft.id):
            return _failure("chapter_local_editor", "中档评审后的本章修订已执行一次", "chapter_review_revision_limit_reached")
        result = await _invoke_json_agent(
            "chapter_local_edit.txt",
            f"======= 完整作品上下文 =======\n{context.content}\n\n"
            f"======= 修订决策 =======\n{decision.content}\n\n"
            f"======= 完整章节草稿 =======\n{draft.content}",
        )
        replacements = result.get("replacements")
        if not isinstance(replacements, list) or not replacements:
            raise ValueError("局部修改缺少替换片段")
        content = draft.content
        skipped_replacements = []
        applied_count = 0
        for item in replacements:
            old = item.get("old") if isinstance(item, dict) else None
            new = item.get("new") if isinstance(item, dict) else None
            if not isinstance(old, str) or not old or not isinstance(new, str):
                raise ValueError("局部修改片段格式无效")
            match_count = content.count(old)
            if match_count != 1:
                skipped_replacements.append({
                    "old": old,
                    "reason": "not_found" if match_count == 0 else "not_unique",
                })
                continue
            content = content.replace(old, new, 1)
            applied_count += 1
        if not applied_count:
            details = "；".join(
                f"“{item['old']}”段在原文中没有找到" if item["reason"] == "not_found"
                else f"“{item['old']}”段在原文中出现多次"
                for item in skipped_replacements
            )
            raise ValueError(f"{details}，没有修改生效。")
        feedback = "；".join(
            f"“{item['old']}”段在原文中没有找到" if item["reason"] == "not_found"
            else f"“{item['old']}”段在原文中出现多次"
            for item in skipped_replacements
        )
        if feedback:
            feedback += "，其他修改已生效。"
        await _write_draft_to_existing_chapter(draft.work_id, draft.chapter_node_id, content)
        artifact = _create_artifact(
            draft.work_id, draft.chapter_node_id, "chapter_draft", content,
            parent_artifact_id=draft.id, version=draft.version + 1,
        )
        if policy:
            policy.record_revision(draft.chapter_node_id or draft.id)
        return _envelope(
            status="completed", agent="chapter_local_editor", artifact=artifact,
            inputs=[context, draft, decision],
            result={
                "strategy": data["strategy"], "replacement_count": applied_count,
                "skipped_replacements": skipped_replacements, "feedback": feedback,
                "word_count_before": len("".join(draft.content.split())),
                "word_count_after": len("".join(content.split())),
            },
            gate_code="local_edit_ready_for_recheck", passed=True,
        )
    except Exception as exc:
        return _failure("chapter_local_editor", str(exc), "chapter_local_edit_failed")


async def _replan_chapter_scenes(context_artifact_id: str, draft_artifact_id: str, decision_artifact_id: str, reason=None) -> str:
    try:
        context, draft, decision, data = _revision_inputs(
            context_artifact_id, draft_artifact_id, decision_artifact_id, "replan"
        )
        policy = _get_chapter_review_policy()
        if policy and not policy.try_reserve_revision(draft.chapter_node_id or draft.id):
            return _failure("chapter_replanner", "中档评审后的本章修订已执行一次", "chapter_review_revision_limit_reached")
        plan = _load_artifact(data["scene_plan_artifact_id"], "scene_plan")
        result = await _invoke_json_agent(
            "chapter_replan.txt",
            f"======= 完整作品上下文 =======\n{context.content}\n\n"
            f"======= 原场景计划 =======\n{plan.content}\n\n"
            f"======= 当前章节草稿 =======\n{draft.content}\n\n"
            f"======= 修订决策 =======\n{decision.content}",
        )
        if not isinstance(result.get("scenes"), list) or not result["scenes"]:
            raise ValueError("重新规划结果缺少场景")
        if not str(result.get("ending_hook") or "").strip():
            raise ValueError("重新规划结果缺少本章结尾")
        artifact = _create_artifact(
            draft.work_id, draft.chapter_node_id, "scene_plan",
            json.dumps(result, ensure_ascii=False), parent_artifact_id=plan.id,
            version=plan.version + 1,
        )
        if policy:
            policy.record_revision(draft.chapter_node_id or draft.id)
        return _envelope(
            status="completed", agent="chapter_replanner", artifact=artifact,
            inputs=[context, plan, draft, decision],
            result={"scene_count": len(result["scenes"]), "ending_hook": result["ending_hook"],
                    "deferred_scenes": result.get("deferred_scenes") or [],
                    "next_chapter_handoff": result.get("next_chapter_handoff") or ""},
            gate_code="scene_replan_ready", passed=True,
        )
    except Exception as exc:
        return _failure("chapter_replanner", str(exc), "chapter_replan_failed")


async def _rewrite_chapter_draft(context_artifact_id: str, draft_artifact_id: str, decision_artifact_id: str, reason=None) -> str:
    try:
        context, draft, decision, data = _revision_inputs(
            context_artifact_id, draft_artifact_id, decision_artifact_id, "rewrite"
        )
        policy = _get_chapter_review_policy()
        if policy and not policy.try_reserve_revision(draft.chapter_node_id or draft.id):
            return _failure("chapter_rewriter", "中档评审后的本章修订已执行一次", "chapter_review_revision_limit_reached")
        plan = _load_artifact(data["scene_plan_artifact_id"], "scene_plan")
        result = await _invoke_json_agent(
            "chapter_rewrite.txt",
            f"======= 完整作品上下文 =======\n{context.content}\n\n"
            f"======= 场景计划 =======\n{plan.content}\n\n"
            f"======= 当前章节草稿 =======\n{draft.content}\n\n"
            f"======= 修订决策 =======\n{decision.content}",
        )
        content = result.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("整章重写结果缺少完整正文")
        await _write_draft_to_existing_chapter(draft.work_id, draft.chapter_node_id, content)
        artifact = _create_artifact(
            draft.work_id, draft.chapter_node_id, "chapter_draft", content,
            parent_artifact_id=draft.id, version=draft.version + 1,
        )
        if policy:
            policy.record_revision(draft.chapter_node_id or draft.id)
        return _envelope(
            status="completed", agent="chapter_rewriter", artifact=artifact,
            inputs=[context, plan, draft, decision],
            result={"strategy": data["strategy"], "word_count_before": len("".join(draft.content.split())),
                    "word_count_after": len("".join(content.split()))},
            gate_code="rewrite_ready_for_recheck", passed=True,
        )
    except Exception as exc:
        return _failure("chapter_rewriter", str(exc), "chapter_rewrite_failed")


class SummaryInput(BaseModel):
    context_artifact_id: str
    draft_artifact_id: str
    reason: Optional[str] = None


async def _summarize_chapter_draft(context_artifact_id: str, draft_artifact_id: str, reason=None) -> str:
    try:
        context = _load_artifact(context_artifact_id, "chapter_context")
        draft = _load_artifact(draft_artifact_id, "chapter_draft")
        result = await _invoke_json_agent(
            "summary.txt",
            f"======= 完整作品上下文 =======\n{context.content}\n\n======= 完整章节正文 =======\n{draft.content}",
        )
        if not str(result.get("summary") or "").strip():
            raise ValueError("章节状态摘要缺少 summary")
        artifact = _create_artifact(
            draft.work_id,
            draft.chapter_node_id,
            "chapter_summary",
            json.dumps(result, ensure_ascii=False),
            parent_artifact_id=draft.id,
        )
        return _envelope(
            status="completed",
            agent="chapter_summary",
            artifact=artifact,
            inputs=[context, draft],
            result=result,
            gate_code="summary_ready",
            passed=True,
        )
    except Exception as exc:
        return _failure("chapter_summary", str(exc), "chapter_summary_failed")


class CommitChapterInput(BaseModel):
    chapter_node_id: str
    draft_artifact_id: str
    summary_artifact_id: Optional[str] = None
    expected_content_sha256: Optional[str] = Field(
        default=None,
        description="装配上下文时正文的 SHA-256，用于识别生成期间的正文修改",
    )
    reason: Optional[str] = None


async def _commit_chapter_workflow_result(
    chapter_node_id: str,
    draft_artifact_id: str,
    summary_artifact_id: str | None = None,
    expected_content_sha256: str | None = None,
    reason: str | None = None,
) -> str:
    db = _get_db()
    try:
        draft = _load_artifact(draft_artifact_id, "chapter_draft")
        summary_artifact = (
            _load_artifact(summary_artifact_id, "chapter_summary")
            if summary_artifact_id else None
        )
        chapter = db.query(Node).filter(Node.id == chapter_node_id, Node.type == "chapter").first()
        if chapter is None:
            return _failure("chapter_commit", "目标章节不存在", "chapter_not_found")
        if draft.chapter_node_id and draft.chapter_node_id != chapter.id:
            return _failure("chapter_commit", "草稿不属于目标章节", "draft_chapter_mismatch")
        if summary_artifact and summary_artifact.chapter_node_id and summary_artifact.chapter_node_id != chapter.id:
            return _failure("chapter_commit", "摘要不属于目标章节", "summary_chapter_mismatch")

        length_result = _draft_length_result(draft)
        if length_result and not length_result["passed"]:
            public_length_result = dict(length_result)
            public_length_result.pop("passed")
            return _envelope(
                status="needs_revision",
                agent="chapter_commit",
                inputs=[draft, *([summary_artifact] if summary_artifact else [])],
                result=public_length_result,
                gate_code="draft_length_revision_required",
                passed=False,
            )

        current_content_sha256 = _content_sha256(chapter.content)
        if expected_content_sha256 and current_content_sha256 != expected_content_sha256 and chapter.content != draft.content:
            return _envelope(
                status="needs_user",
                agent="chapter_commit",
                inputs=[draft, *([summary_artifact] if summary_artifact else [])],
                result={
                    "expected_content_sha256": expected_content_sha256,
                    "current_content_sha256": current_content_sha256,
                    "reason": "生成期间章节已发生修改",
                },
                gate_code="chapter_version_conflict",
                passed=False,
                user_decision={
                    "question": "生成期间章节已经修改，需要决定保留当前正文还是提交生成稿。",
                    "options": ["保留当前正文", "写入生成稿"],
                },
            )

        old_content = chapter.content or ""
        chapter.updated_at = datetime.utcnow()
        summary_data = _json_content(summary_artifact) if summary_artifact else {}
        from services.node_content_write_service import write_node_content
        write_node_content(
            db,
            chapter,
            draft.content,
            summary=str(summary_data.get("summary") or ""),
            status="generated",
        )
        db.commit()
        db.refresh(chapter)
        result = _envelope(
            status="completed",
            agent="chapter_commit",
            inputs=[draft, *([summary_artifact] if summary_artifact else [])],
            result={
                "chapter_node_id": chapter.id,
                "draft_version": draft.version,
                "word_count": len("".join(draft.content.split())),
                "summary_saved": bool(summary_artifact),
                "updated_at": chapter.updated_at.isoformat() if chapter.updated_at else None,
            },
            gate_code="chapter_committed",
            passed=True,
        )
        emit = _get_emit()
        if emit:
            await emit("nodes_updated", {
                "action": "chapter_commit",
                "chapter_node_id": chapter.id,
                "content_changed": True,
            })
            from services.chapter_edit_service import build_content_diff
            from services.agents.tools.node_tools import _content_diff_event

            content_diff = {
                "diff": build_content_diff(old_content, draft.content),
                "old_content": old_content,
                "new_content": draft.content,
            }
            if content_diff["diff"].get("hunks"):
                event_name, event_data = _content_diff_event(
                    {"id": chapter.id, "type": "chapter", "title": chapter.title},
                    content_diff,
                )
                await emit(event_name, event_data)
        return result
    except Exception as exc:
        db.rollback()
        return _failure("chapter_commit", str(exc), "chapter_commit_failed")
    finally:
        db.close()


load_write_chapter_skill = StructuredTool.from_function(
    coroutine=_load_write_chapter_skill,
    name="load_write_chapter_skill",
    description="写作或续写完整章节前，完整加载 write-chapter Workflow Skill。",
    args_schema=LoadSkillInput,
)
assemble_chapter_context = StructuredTool.from_function(
    coroutine=_assemble_chapter_context,
    name="assemble_chapter_context",
    description=(
        "按目标章节装配完整作品上下文并返回可传给专职 Agent 的产物引用。"
        "已有章节只传 chapter_node_id；尚无章节则传 parent_node_id（必须是 plot）、"
        "chapter_title、sort_order，由本工具创建空章节并建立 contains 连线。"
        "两组参数互斥。"
    ),
    args_schema=AssembleContextInput,
)
plan_chapter_scenes = StructuredTool.from_function(
    coroutine=_plan_chapter_scenes,
    name="plan_chapter_scenes",
    description="调用场景规划专职 Agent，返回结构化场景计划产物与质量门结果。",
    args_schema=ArtifactInput,
)
prepare_chapter_from_scene_plan = StructuredTool.from_function(
    coroutine=_prepare_chapter_from_scene_plan,
    name="prepare_chapter_from_scene_plan",
    description=(
        "读取 scene_plan Artifact，确定性同步章节 chapter_elements 和已存在角色引用；"
        "保持章节 content 不变。"
    ),
    args_schema=PrepareChapterInput,
)
write_chapter_draft = StructuredTool.from_function(
    coroutine=_write_chapter_draft,
    name="write_chapter_draft",
    description="调用正文写作专职 Agent，根据完整上下文和场景计划生成版本化完整草稿。",
    args_schema=WriteDraftInput,
)
review_chapter_continuity = StructuredTool.from_function(
    coroutine=_review_chapter_continuity,
    name="review_chapter_continuity",
    description="调用连续性 Reviewer，返回证据、修改范围和结构化质量门结果。",
    args_schema=ReviewInput,
)
review_chapter_dialogue = StructuredTool.from_function(
    coroutine=_review_chapter_dialogue,
    name="review_chapter_dialogue",
    description="调用对白 Reviewer，检查人物声音、交流目的、潜台词、信息权限和互动节奏。",
    args_schema=ReviewInput,
)
revise_chapter_draft = StructuredTool.from_function(
    coroutine=_revise_chapter_draft,
    name="revise_chapter_draft",
    description="调用定向修订 Agent，根据审查产物生成新的完整草稿版本，完成后应由对应 Reviewer 复检。",
    args_schema=ReviseDraftInput,
)
decide_chapter_revision = StructuredTool.from_function(
    coroutine=_decide_chapter_revision,
    name="decide_chapter_revision",
    description="根据完整场景计划、当前草稿和修改反馈，选择重新规划、整章重写或局部修改，并说明原因。",
    args_schema=RevisionDecisionInput,
)
edit_chapter_draft_locally = StructuredTool.from_function(
    coroutine=_edit_chapter_draft_locally,
    name="edit_chapter_draft_locally",
    description="根据修订决策生成精确原文替换片段，只修改命中的局部正文并保存新版本。",
    args_schema=ExecuteRevisionInput,
)
replan_chapter_scenes = StructuredTool.from_function(
    coroutine=_replan_chapter_scenes,
    name="replan_chapter_scenes",
    description="根据修订决策重新划定本章场景边界，保存新的场景计划及下一章交接信息。",
    args_schema=ExecuteRevisionInput,
)
rewrite_chapter_draft = StructuredTool.from_function(
    coroutine=_rewrite_chapter_draft,
    name="rewrite_chapter_draft",
    description="根据修订决策与原计划重写完整章节，保存新的草稿版本。",
    args_schema=ExecuteRevisionInput,
)
summarize_chapter_draft = StructuredTool.from_function(
    coroutine=_summarize_chapter_draft,
    name="summarize_chapter_draft",
    description="调用摘要 Agent，从已通过验收的草稿提取章节摘要与章末状态。",
    args_schema=SummaryInput,
)
commit_chapter_workflow_result = StructuredTool.from_function(
    coroutine=_commit_chapter_workflow_result,
    name="commit_chapter_workflow_result",
    description="把通过质量门的最新草稿和摘要正式提交到目标章节；使用装配上下文时的正文 SHA-256 检测并发修改。",
    args_schema=CommitChapterInput,
)


specialist_agent_tools = [
    load_write_chapter_skill,
    assemble_chapter_context,
    plan_chapter_scenes,
    prepare_chapter_from_scene_plan,
    write_chapter_draft,
    review_chapter_continuity,
    review_chapter_dialogue,
    revise_chapter_draft,
    decide_chapter_revision,
    edit_chapter_draft_locally,
    replan_chapter_scenes,
    rewrite_chapter_draft,
    summarize_chapter_draft,
    commit_chapter_workflow_result,
]
