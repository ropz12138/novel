"""章节规划 Skill 的加载边界与直接写章契约。"""
import asyncio
import json

import pytest

from services.agents.tools import workflow_skill_tools as workflow


def test_scene_planning_skill_loads_complete_reference_without_model(monkeypatch):
    from services.agents import llm

    def unexpected_model(**kwargs):
        pytest.fail("规划规则读取应由 Supervisor 当前上下文执行")

    monkeypatch.setattr(llm, "get_llm", unexpected_model)
    monkeypatch.setattr(llm, "get_deep_agent_model", unexpected_model)
    result = json.loads(asyncio.run(workflow.load_workflow_skill.ainvoke(
        {"skill_name": "plan-chapter-scenes"}
    )))
    assert result["success"]
    assert result["skill_content"] == (
        workflow.SKILLS_ROOT / "plan-chapter-scenes" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert result["references"] == ["scene_plan.txt"]
    reference = json.loads(asyncio.run(workflow.read_skill_reference.ainvoke(
        {"skill_name": "plan-chapter-scenes", "reference_name": "scene_plan.txt"}
    )))
    assert reference["success"]
    assert reference["content"] == (
        workflow.REFERENCE_ROOT / "scene_plan.txt"
    ).read_text(encoding="utf-8")


def test_planning_skill_is_routed_from_supervisor_and_writing_workflow():
    root = workflow.SKILLS_ROOT.parent
    supervisor = (root / "prompts" / "supervisor_system.txt").read_text(encoding="utf-8")
    writing = (workflow.SKILLS_ROOT / "write-chapter" / "SKILL.md").read_text(encoding="utf-8")
    revision = (workflow.SKILLS_ROOT / "revise-chapter" / "SKILL.md").read_text(encoding="utf-8")
    for instruction in (supervisor, writing, revision):
        assert "`plan-chapter-scenes`" in instruction
        assert "任务说明" in instruction
        assert "update_node" in instruction


def test_write_chapter_skill_points_at_complete_writer_rules():
    skill = (workflow.SKILLS_ROOT / "write-chapter" / "SKILL.md").read_text(encoding="utf-8")
    rules = (workflow.REFERENCE_ROOT / "chapter_writer.txt").read_text(encoding="utf-8")
    assert "chapter_writer.txt" in skill
    assert "update_node" in skill
    assert "run_writing_agent" not in skill
    assert "write_content" not in rules
    assert "finish_writing" not in rules


def test_scene_plan_keeps_markdown_plan_structure():
    plan = (workflow.REFERENCE_ROOT / "scene_plan.txt").read_text(encoding="utf-8")
    assert "事实清楚、因果连续" in plan
    assert "run_writing_agent" not in plan
