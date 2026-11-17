"""Writer 接入保留现有 V3 系统提示词及各 Skill 的参考研究约定。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'services' / 'agents'


def test_writer_integration_preserves_current_supervisor_reference_policy():
    prompt = (ROOT / 'prompts/supervisor_system.txt').read_text()
    assert '# 七、参考研究：按需，而非强制' in prompt
    assert '`run_reference_agent` 仅在当前工具集中可用且参考研究能够解决具体问题时调用' in prompt
    assert '作者要求借鉴某类作品、场景、节奏或叙事技法' in prompt
    assert '核心方向变化时再判断是否需要新检索' in prompt
    assert '研究结论只是方法参考，而不是高于正文和设定的事实' in prompt


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
