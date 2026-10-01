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
    assert "章节正文以 3000 字为目标" not in PROMPT
    assert "2500–3500 字" not in PROMPT
    assert "`write_chapter`" not in PROMPT
    assert "`edit_chapter_content`" not in PROMPT
    assert "尚无章节则传 `parent_node_id`" in PROMPT
    assert "由该工具创建空章节并建立 plot→chapter 的 contains 连线" in PROMPT
    assert "`prepare_chapter_from_scene_plan`" in PROMPT
    assert "先调用 `decide_chapter_revision`" in PROMPT


def test_prompt_limits_word_count_adjustment_to_two_attempts():
    assert "针对字数的调整，每次执行最多两次" in PROMPT
    assert "两次之后仍未达到目标字数，停止继续删改" in PROMPT


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
    assert "Supervisor 阅读评审建议和证据" in skill
    assert "每个评审工具最多调用一次" in skill
    assert "评审次数不限" in skill
    assert "85%" not in skill
    assert "115%" not in skill
    assert "不要自动循环压缩篇幅" in skill


def test_revise_chapter_skill_does_not_force_word_count_loop():
    skill = (
        Path(__file__).resolve().parents[1]
        / "services/agents/skills/revise-chapter/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "`count_chapter_words`" in skill
    assert "`decide_chapter_revision`" in skill
    assert "`edit_chapter_draft_locally`" in skill
    assert "85%" not in skill
    assert "115%" not in skill
    assert "不要自动循环压缩篇幅" in skill


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


def test_prompt_requires_brief_final_user_reply():
    assert "给用户的最终回答必须简略" in PROMPT
    assert "控制在几句话以内" in PROMPT
    assert "不要复述章节正文" in PROMPT
    assert "场景规划" in PROMPT
    assert "评审意见" in PROMPT


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


def test_prompt_requires_active_note_maintenance():
    assert "## 笔记维护" in PROMPT
    assert "`get_canvas_index`" in PROMPT
    assert 'type="note"' in PROMPT
    assert "不得只把需求留在对话里" in PROMPT
    assert "同一主题只维护一个笔记节点" in PROMPT
    assert "回读" in PROMPT
    skill = (
        Path(__file__).resolve().parents[1]
        / "services/agents/skills/bootstrap-novel/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "`note`" in skill
    architect = (
        Path(__file__).resolve().parents[1]
        / "services/agents/prompts/specialists/premise_architect.txt"
    ).read_text(encoding="utf-8")
    assert "`note`" in architect
    assert "用户提出的需求" in architect


def _chapter_writer_shared_rules(writer: str) -> str:
    start = writer.index("# 二、角色视角与信息边界")
    output = writer.index("# 二十三、输出格式")
    principles = writer.index("# 二十四、最终写作原则")
    return writer[start:output].rstrip() + "\n\n" + writer[principles:].rstrip() + "\n"


def test_prose_writing_prompts_share_chapter_writer_style_rules():
    specialists = Path(__file__).resolve().parents[1] / "services/agents/prompts/specialists"
    writer = (specialists / "chapter_writer.txt").read_text(encoding="utf-8")
    shared = _chapter_writer_shared_rules(writer)
    assert "# 十、避免孤立状态句与伪镜头式短句" in shared
    assert "# 二十、避免 AI 文学腔的重点规则" in shared
    assert "# 二十三、输出格式" not in shared
    for name in (
        "chapter_rewrite.txt",
        "chapter_local_edit.txt",
        "revision.txt",
        "existing_chapter_revision.txt",
        "humanizer_agent.txt",
    ):
        prompt = (specialists / name).read_text(encoding="utf-8")
        assert prompt.endswith(shared)
        assert "# 二十三、输出格式" not in prompt


def test_writing_prompts_require_character_pov_analysis():
    specialists = Path(__file__).resolve().parents[1] / "services/agents/prompts/specialists"
    required = "必须先站在该角色的角度，结合其性格与当时的处境"
    dialogue_review = (specialists / "dialogue_review.txt").read_text(encoding="utf-8")
    assert required in dialogue_review
    assert "禁止用作者旁白代替角色本人的取舍" in dialogue_review

    scene_plan = (specialists / "scene_plan.txt").read_text(encoding="utf-8")
    assert "character_goal、known_information、choice、consequence" in scene_plan
    assert "人物身份与认知范围和上下文一致" in scene_plan
    assert "具体台词、成品心理句和文学表达由正文阶段生成" in scene_plan
    for name in (
        "chapter_writer.txt",
        "chapter_rewrite.txt",
        "chapter_local_edit.txt",
        "revision.txt",
        "existing_chapter_revision.txt",
        "humanizer_agent.txt",
    ):
        prompt = (specialists / name).read_text(encoding="utf-8")
        assert "# 二、角色视角与信息边界" in prompt
        assert "不要让角色拥有作者级别的信息整合能力。" in prompt


def test_chapter_writer_treats_scene_plan_as_facts_instead_of_draft_prose():
    prompt = (
        Path(__file__).resolve().parents[1]
        / "services/agents/prompts/specialists/chapter_writer.txt"
    ).read_text(encoding="utf-8")
    assert "场景计划提供的是事实、目标、选择、后果和信息变化" in prompt
    assert "根据现场语境独立完成具体措辞、句式、心理呈现和叙述节奏" in prompt
