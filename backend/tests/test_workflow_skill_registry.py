import asyncio
import json
from pathlib import Path

from services.agents.supervisor import SupervisorAgent
from services.agents.tools import workflow_agent_tools as wat


EXPECTED_SKILLS = {
    "bootstrap-novel", "design-worldbuilding", "design-characters",
    "plan-outline", "plan-story-structure", "write-chapter", "revise-chapter",
    "humanize-fiction", "evaluate-fiction", "maintain-story-memory", "apply-research",
}

EXPECTED_TOOLS = {
    "load_workflow_skill", "assemble_work_context", "review_artifact_quality",
    "develop_existing_nodes", "stage_existing_chapter_draft",
    "revise_existing_chapter_draft", "humanize_chapter_draft",
    "review_fiction_quality", "review_novel_coherence", "extract_story_memory",
    "resolve_research_context", "apply_research_techniques",
}


def test_all_workflow_skills_are_discoverable_and_load_in_full():
    assert set(wat.WORKFLOW_SKILLS) == EXPECTED_SKILLS
    for skill_name in EXPECTED_SKILLS:
        result = json.loads(asyncio.run(wat.load_workflow_skill.ainvoke({"skill_name": skill_name})))
        assert result["success"] is True
        assert result["result"]["skill_name"] == skill_name
        assert "完成标准" in result["result"]["skill_content"]
        assert "执行流程" in result["result"]["skill_content"]


def test_all_workflow_agent_tools_are_registered_on_supervisor():
    names = {tool.name for tool in SupervisorAgent()._get_tools()}
    assert EXPECTED_TOOLS <= names
    assert not any("candidate" in name for name in names)


def test_skill_loader_rejects_unknown_skill_without_fallback():
    result = json.loads(asyncio.run(wat.load_workflow_skill.ainvoke({"skill_name": "unknown-skill"})))
    assert result["success"] is False
    assert result["gate"]["code"] == "workflow_skill_not_found"


def test_supervisor_routes_structural_writing_to_real_nodes():
    prompt_path = Path(__file__).parents[1] / "services" / "agents" / "prompts" / "supervisor_system.txt"
    prompt = prompt_path.read_text(encoding="utf-8")
    for skill_name in EXPECTED_SKILLS:
        assert f"`{skill_name}`" in prompt
    assert "`develop_existing_nodes`" in prompt
    assert "建立真实节点" in prompt
    assert "按 UUID 写入节点数据" in prompt
    assert "candidate_key" not in prompt
