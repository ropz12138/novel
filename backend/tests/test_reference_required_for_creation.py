"""New creative work always includes a current reference-agent research stage."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'services' / 'agents'


def test_supervisor_requires_reference_even_for_a_complete_existing_plan():
    prompt = (ROOT / 'prompts/supervisor_system.txt').read_text()
    assert '新内容的设计与创作必须经过参考研究' in prompt
    assert '工具集中有 `run_reference_agent` 时' in prompt
    assert '本轮未取回章节原文时' in prompt
    assert '作者或既有规划已经明确完整事件链时，你直接核对并本作化落实' not in prompt
    assert '尚未固定完整事件链时' not in prompt
    assert '作者已经提供完整事件链' in prompt
    assert '参考材料就绪后继续' not in prompt
    assert '取得成功结果' not in prompt
    assert '章节原文' in prompt
    assert '叙事机制和适配方向' not in prompt


def test_all_creation_skills_include_the_reference_prerequisite():
    for skill in ('bootstrap-novel', 'design-worldbuilding', 'design-characters',
                  'plan-story-structure', 'plan-chapter-scenes', 'write-chapter'):
        text = (ROOT / 'skills' / skill / 'SKILL.md').read_text()
        assert 'run_reference_agent' in text, skill
        assert '必经环节' in text, skill
        assert '本轮未取回章节原文时' in text, skill
        assert '参考材料就绪后继续' not in text, skill
        assert '选择机制并完成本作化' not in text, skill
    revision = (ROOT / 'skills/revise-chapter/SKILL.md').read_text()
    assert '新增' in revision and 'run_reference_agent' in revision
    assert '本轮未取回章节原文时' in revision
    assert '材料就绪后继续' not in revision
    writing = (ROOT / 'skills/write-chapter/SKILL.md').read_text()
    assert '尚未给出完整具体事件链' not in writing
    scene_plan = (ROOT / 'skills/references/scene_plan.txt').read_text()
    assert '本轮未取回章节原文时' in scene_plan
