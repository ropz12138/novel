"""灵感孵化、渐进式大纲、世界观生态衍生与非主线节奏血肉提示词测试（TDD）。"""
from pathlib import Path


AGENTS_ROOT = Path(__file__).resolve().parents[1] / "services" / "agents"
PROMPTS_ROOT = AGENTS_ROOT / "prompts"
SKILLS_ROOT = AGENTS_ROOT / "skills"
REFERENCES_ROOT = SKILLS_ROOT / "references"


def test_supervisor_prompt_supports_seed_incubation_and_experiential_options():
    prompt = (PROMPTS_ROOT / "supervisor_system.txt").read_text(encoding="utf-8")

    # 支持从局部世界观或小场景片段孵化，并向非作者用户提供具体名场面与体验化方案
    assert "局部世界观" in prompt or "场景片段" in prompt
    assert "名场面" in prompt
    assert "阅读体验" in prompt or "读者体验" in prompt

    # 根据具体作品题材、阶段与近期章节节奏动态调配主线与非主线血肉
    assert "根据具体作品" in prompt
    assert "日常切片" in prompt
    assert "世界风物" in prompt
    assert "支线" in prompt


def test_bootstrap_and_outline_skills_use_progressive_near_far_planning():
    bootstrap_skill = (SKILLS_ROOT / "bootstrap-novel" / "SKILL.md").read_text(encoding="utf-8")
    premise_ref = (REFERENCES_ROOT / "premise_architect.txt").read_text(encoding="utf-8")
    outline_skill = (SKILLS_ROOT / "plan-outline" / "SKILL.md").read_text(encoding="utf-8")
    outline_ref = (REFERENCES_ROOT / "outline_plan.txt").read_text(encoding="utf-8")

    # 从小想法/局部世界观/场景片段反推孵化，保留种子核心画面感与趣味
    assert "场景片段" in bootstrap_skill
    assert "场景片段" in premise_ref
    assert "反推" in premise_ref

    # 近景具体可感 + 远景锚点，避免中后期空泛流水账
    assert "近景" in premise_ref and "远景" in premise_ref
    assert "近景" in outline_ref and "远景" in outline_ref
    assert "流水账" in outline_ref
    assert "远景锚点" in outline_skill


def test_worldbuilding_derives_social_ecology_and_side_story_hooks():
    wb_skill = (SKILLS_ROOT / "design-worldbuilding" / "SKILL.md").read_text(encoding="utf-8")
    wb_ref = (REFERENCES_ROOT / "worldbuilding.txt").read_text(encoding="utf-8")

    assert "不完整世界观" in wb_skill or "局部设定" in wb_skill
    assert "社会生态" in wb_ref
    assert "日常" in wb_ref
    assert "风物" in wb_ref
    assert "支线钩子" in wb_ref


def test_story_structure_and_scene_plan_adapt_non_mainline_pacing_by_work():
    structure_skill = (SKILLS_ROOT / "plan-story-structure" / "SKILL.md").read_text(encoding="utf-8")
    structure_ref = (REFERENCES_ROOT / "story_structure.txt").read_text(encoding="utf-8")
    chapter_plan_ref = (REFERENCES_ROOT / "chapter_plan.txt").read_text(encoding="utf-8")
    scene_skill = (SKILLS_ROOT / "plan-chapter-scenes" / "SKILL.md").read_text(encoding="utf-8")
    scene_ref = (REFERENCES_ROOT / "scene_plan.txt").read_text(encoding="utf-8")

    # 根据具体作品题材、阶段与相邻章节密度动态调配主线与非主线内容
    assert "根据具体作品" in structure_ref
    assert "日常切片" in chapter_plan_ref
    assert "世界风物" in chapter_plan_ref
    assert "收获盘点" in chapter_plan_ref or "战后消化" in chapter_plan_ref
    assert "支线" in structure_skill

    # 场景规划对非攻坚场景解绑机械敌对阻力，支持好奇探索、设定趣味与关系互动
    assert "日常切片" in scene_skill or "世界风物" in scene_skill
    assert "非功利" in scene_ref or "非攻坚" in scene_ref
    assert "世界风物" in scene_ref
    assert "好奇" in scene_ref or "趣味" in scene_ref


def test_chapter_writer_preserves_meaningful_idle_strokes_and_world_texture():
    writer_ref = (REFERENCES_ROOT / "chapter_writer.txt").read_text(encoding="utf-8")

    assert "闲笔" in writer_ref
    assert "风物" in writer_ref
    assert "生活气息" in writer_ref


def test_reference_agent_and_story_memory_support_non_mainline_callbacks():
    reference_prompt = (PROMPTS_ROOT / "reference_agent_system.txt").read_text(encoding="utf-8")
    memory_skill = (SKILLS_ROOT / "maintain-story-memory" / "SKILL.md").read_text(encoding="utf-8")
    memory_ref = (REFERENCES_ROOT / "story_memory.txt").read_text(encoding="utf-8")
    summary_ref = (REFERENCES_ROOT / "summary.txt").read_text(encoding="utf-8")

    # 情节参考 Agent 支持检索日常切片、风物展示、战后盘点与支线插曲机制
    assert "日常切片" in reference_prompt
    assert "风物" in reference_prompt
    assert "支线" in reference_prompt

    # 故事记忆记录闲笔锚点与潜在支线钩子供后续回扣（闲笔不闲）
    assert "风物锚点" in memory_skill or "支线钩子" in memory_skill
    assert "支线钩子" in memory_ref
    assert "风物锚点" in summary_ref or "支线钩子" in summary_ref
