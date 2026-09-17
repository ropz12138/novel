"""Supervisor 章节工作流提示词测试。"""
from pathlib import Path


PROMPT = (
    Path(__file__).resolve().parents[1]
    / "services/agents/prompts/supervisor_system.txt"
).read_text(encoding="utf-8")


def test_prompt_limits_node_types():
    for node_type in ("character", "outline", "volume", "plot", "chapter", "worldbuilding", "note"):
        assert f"`{node_type}`" in PROMPT
    assert "`note`" in PROMPT
    assert "`style`" not in PROMPT
    assert "任何需求" in PROMPT
    assert "- `element`" not in PROMPT
    assert "`chapter_elements`" in PROMPT
    assert "`storylines`" in PROMPT
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
    assert "write_todolist" not in PROMPT
    assert "update_todolist" not in PROMPT
    assert "章节正文以 3000 字为目标" in PROMPT
    assert "2500–3500 字" in PROMPT
    assert "`write_chapter`" not in PROMPT
    assert "`edit_chapter_content`" not in PROMPT
    assert "尚无章节则传 `parent_node_id`" in PROMPT
    assert "由该工具创建空章节并建立 plot→chapter 的 contains 连线" in PROMPT
    assert "`prepare_chapter_from_scene_plan`" in PROMPT
    assert "先调用 `decide_chapter_revision`" in PROMPT


def test_write_chapter_skill_routes_each_revision_through_strategy_decision():
    skill = (
        Path(__file__).resolve().parents[1]
        / "services/agents/skills/write-chapter/SKILL.md"
    ).read_text(encoding="utf-8")

    for tool_name in (
        "decide_chapter_revision", "replan_chapter_scenes",
        "rewrite_chapter_draft", "edit_chapter_draft_locally",
    ):
        assert f"`{tool_name}`" in skill
    assert "每出现新一轮修改需求" in skill


def test_removed_operational_rules_are_available_from_registered_tools():
    from services.agents.supervisor import SupervisorAgent

    tools = {tool.name: tool for tool in SupervisorAgent()._get_tools()}

    create_schema_text = str(tools["create_node"].args_schema.model_json_schema())
    assert "element 不再是节点类型" in create_schema_text
    assert "chapter_elements" in create_schema_text
    assert "storylines" in create_schema_text

    update_schema_text = str(tools["update_node"].args_schema.model_json_schema())
    update_tool_text = tools["update_node"].description + update_schema_text
    assert "content_edit_instruction" not in update_tool_text
    assert "完整正文" in update_tool_text
    assert "content_edit_instruction" not in PROMPT

    assert "write_todolist" not in tools
    assert "先 read_node_content" in tools["insert_chapter_illustration"].description
    assert "final_report" in tools["list_research_artifacts"].description
    assert "[C1]" in tools["create_context_compaction"].description
    assert "[C...]" in tools["resolve_context_source"].description


def test_prompt_requires_dedicated_plot_markers_and_post_write_review():
    assert "`[[PLOT]]正文中已有的连续原文[[/PLOT]]`" in PROMPT
    assert "Markdown 的 `**...**` 仅表示普通粗体" in PROMPT
    assert "必须调用 `read_node_content` 重新读取已保存的整章正文" in PROMPT
    assert "高亮采用正文中已经存在的连续原文" in PROMPT
    assert "高亮的数量和长度由剧情表达需要决定" in PROMPT
    assert "微型章节梗概" not in PROMPT
    assert "`plot_highlight_validation`" not in PROMPT


def test_prompt_leaves_layout_to_frontend():
    """布局由前端按可见子图自动计算，提示词不再指导 Agent 摆放坐标。"""
    assert "## 布局建议" not in PROMPT
    from node_types import NODE_LAYOUT_RULES_TEXT
    assert "前端" in NODE_LAYOUT_RULES_TEXT
    assert "画布左侧" not in NODE_LAYOUT_RULES_TEXT
    assert "不会自动重排" not in NODE_LAYOUT_RULES_TEXT
    assert "element" not in NODE_LAYOUT_RULES_TEXT


def test_prompt_explains_how_to_use_research_artifacts():
    assert "研究成果只提供写作方法参考" in PROMPT
    assert "不得把参考小说的人名" in PROMPT
