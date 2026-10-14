"""章节规划 Skill 的加载边界与 Writer 交接契约。"""
import asyncio
import json

import pytest

from services.agents.tools import workflow_skill_tools as workflow
from services.agents.tools.writing_agent_tools import WritingBrief


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
        assert "brief.scene_plan" in instruction


def test_writer_receives_full_operation_rules_and_planning_guidance():
    from services.agents.tools.writing_agent_tools import PROMPT_PATH, _writer_prompt

    writer = PROMPT_PATH.read_text(encoding="utf-8")
    rules = (workflow.REFERENCE_ROOT / "chapter_writer.txt").read_text(encoding="utf-8")
    assembled = _writer_prompt("write")
    assert rules in assembled
    assert assembled.endswith(writer)


def test_scene_plan_survives_existing_writer_brief_round_trip():
    plan = {
        "chapter_goal": "获得带队条件",
        "reader_expectation": "主角如何应对借刀杀人",
        "chapter_payoff": "用承担风险换取战利品分配权",
        "effective_obstacle": "王强控制人手与仓库钥匙",
        "ending_change": "双方达成附带条件的合作",
        "scenes": [{
            "title": "会议交锋",
            "participant_goals": [
                {"character": "王强", "goal": "让陆沉承担风险并交回物资"},
                {"character": "陆沉", "goal": "取得猎核机会和分配权"},
            ],
            "pressure": "拒绝带队会失去获取物资的机会",
            "choice": "接受带队并提出战利品条件",
            "consequence": "王强让步但将亲信编入队伍",
            "reader_experience": "受压到扳回筹码，合作仍有风险",
        }],
    }
    encoded = json.dumps(plan, ensure_ascii=False)
    brief = WritingBrief(
        scene_plan=encoded, narrative_pov="陆沉有限视角",
        character_knowledge=[{"character": "陆沉", "known_information": "食堂缺粮",
                              "source": "会议中听王强说明"}],
        story_facts="王强管理仓库", prose_requirements="完整作者要求",
        revision_scope="创作空章节",
    )
    restored = WritingBrief.model_validate_json(brief.model_dump_json())
    assert restored.scene_plan == encoded
    assert json.loads(restored.scene_plan) == plan
