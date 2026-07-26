"""Supervisor 章节工作流提示词测试。"""
from pathlib import Path


PROMPT = (
    Path(__file__).resolve().parents[1]
    / "app/services/agents/prompts/supervisor_system.txt"
).read_text(encoding="utf-8")


def test_prompt_limits_node_types():
    for node_type in ("character", "outline", "volume", "plot", "chapter", "worldbuilding", "style"):
        assert f"`{node_type}`" in PROMPT
    assert "不要创建 `element` 节点" in PROMPT
    assert "- `element`" not in PROMPT
    assert "`chapter_elements`" in PROMPT
    for removed in (
        "event", "idea", "setting", "conflict", "foreshadow", "theme",
        "macro_outline", "meso_outline", "micro_outline", "core_idea",
    ):
        assert f"`{removed}`" not in PROMPT


def test_prompt_removed_sections():
    assert "## 你的能力" not in PROMPT
    assert "## 决策规则" not in PROMPT
    assert "## 角色定位" not in PROMPT
    assert "## 评估章节" not in PROMPT
    assert "## 章节插画" not in PROMPT
    assert "## 任务清单" not in PROMPT
    assert "## 布局自检" not in PROMPT
    assert "## 连线连接点" not in PROMPT
    assert "{global_context}" not in PROMPT
    assert "{canvas_overview}" not in PROMPT
    assert "{user_message}" not in PROMPT


def test_prompt_keeps_workflow():
    assert "## 创作工作流" in PROMPT
    assert "`update_node`" in PROMPT
    assert "`content_edit_instruction`" in PROMPT
    assert "`write_chapter`" not in PROMPT
    assert "`edit_chapter_content`" not in PROMPT
    assert "`write_todolist`" in PROMPT


def test_prompt_keeps_layout_in_tools_not_system():
    assert "## 布局建议" not in PROMPT
    from app.node_types import NODE_LAYOUT_RULES_TEXT
    assert "character" in NODE_LAYOUT_RULES_TEXT
    assert "style" in NODE_LAYOUT_RULES_TEXT
    assert "outline/volume/plot/chapter" in NODE_LAYOUT_RULES_TEXT
    assert "element" not in NODE_LAYOUT_RULES_TEXT
