from pathlib import Path


PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "agents"
    / "prompts"
    / "research_system.txt"
)


def test_research_prompt_prioritizes_reusable_techniques_over_plot_summary():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "禁止把逐章剧情摘要" in prompt
    assert "研究对象始终是“作者如何写”" in prompt
    assert "不再强制生成 `reading_note`" in prompt
    assert "作者的叙事手法" in prompt
    assert "角色塑造" in prompt
    assert "剧情推动事件" in prompt
    assert "情节结构与节奏" in prompt
    assert "场景与表达" in prompt
    assert "作者的稳定偏好" in prompt
    assert "读完一批必须保存一份 `reading_note`" not in prompt


def test_research_prompt_rejects_in_world_system_analysis_as_technique():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "技能强弱、装备收益、任务奖励、职业搭配、力量体系合理性" in prompt
    assert "不能直接命名为写作技法" in prompt
    assert "故事层" in prompt
    assert "作者层" in prompt
    assert "叙事结果层" in prompt
    assert "禁止用小说内部名词直接命名" in prompt
    assert "同一技能或设定反复出现不计为作者动作重复" in prompt
    assert "如果删掉小说中的专有名词后" in prompt


def test_research_prompt_requires_six_author_level_final_sections():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "final_report 必须设置六个主体部分" in prompt
    assert "主要角色如何被写出来" in prompt
    assert "怎样改变目标、处境、关系或认知" in prompt
    assert "重复模式、效果、反例和缺点" in prompt


def test_research_prompt_forbids_guessed_paths_and_empty_globs():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "绝对禁止根据剧情记忆猜测完整文件标题" in prompt
    assert "禁止传 `glob_pattern=null`" in prompt
    assert "chapters/manifest.tsv" in prompt
    assert "每批完成后必须调用 update_research_progress" in prompt
