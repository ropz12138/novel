"""Supervisor 章节工作流提示词测试。"""
from pathlib import Path


PROMPT = (
    Path(__file__).resolve().parents[1]
    / "services/agents/prompts/supervisor_system.txt"
).read_text(encoding="utf-8")


def test_prompt_states_markdown_for_non_chapter_content_and_chapter_notes():
    assert "非章节节点可用 Markdown，章节正文保持小说排版。" in PROMPT
    assert "每个 `replacement` 包含 `start_paragraph`、`end_paragraph`、`new`；编号必须来自本次最新读取的 `content_paragraphs`。" in PROMPT
    assert "小说正文必须输出 Markdown" not in PROMPT


def test_prompt_limits_node_types():
    for node_type in ("character", "chapter", "worldbuilding", "note", "reviewer_note"):
        assert f"`{node_type}`" in PROMPT
    assert "`note`" in PROMPT
    assert "`style`" not in PROMPT
    assert "持续生效" in PROMPT
    assert "- `element`" not in PROMPT
    assert "`chapter_elements`" not in PROMPT
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
    assert "# 八、写作一章的标准工作流" in PROMPT
    assert "read_todolist" in PROMPT
    assert "update_todolist" in PROMPT
    assert "章节正文以 3000 字为目标" not in PROMPT
    assert "2500–3500 字" not in PROMPT
    assert "`write_chapter`" not in PROMPT
    assert "`edit_chapter_content`" not in PROMPT
    assert "新章节用 `create_node` 创建 `content` 为空的 `chapter`" in PROMPT
    assert "设置真实作品内 `sort_order`" in PROMPT
    assert "`chapter_elements`" not in PROMPT
    assert "`save_chapter_notes`" in PROMPT
    assert "`save_workflow_record`" not in PROMPT
    assert "`read_workflow_records`" not in PROMPT


def test_prompt_limits_word_count_adjustment_to_two_attempts():
    assert "否则默认约 2000 字" in PROMPT
    assert "章节整章新写或整章重写后，调用 `count_chapter_words`" in PROMPT
    assert "篇幅调整最多两轮" in PROMPT
    assert "仍有明显差距时如实说明" in PROMPT
    writer = (
        Path(__file__).resolve().parents[1]
        / "services/agents/skills/references/chapter_writer.txt"
    ).read_text(encoding="utf-8")
    writing = (
        Path(__file__).resolve().parents[1]
        / "services/agents/skills/write-chapter/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "默认篇幅为 2000 字左右" in writer
    assert "默认 2000 字左右" in writing


def test_prompt_analyzes_requests_and_offers_meaningful_choices():
    assert "# 三、作者意图、方案选择与决策权限" in PROMPT
    assert "先辨认这是事实查询、讨论建议、设定维护、故事规划、章节新写、局部修改、整章重写、自然化还是独立评审。" in PROMPT
    assert "提供 2—3 个真正不同的可执行方案" in PROMPT
    assert "并推荐一个" in PROMPT
    assert "关键信息足够时，直接执行" in PROMPT


def test_revise_chapter_skill_does_not_force_word_count_loop():
    skill = (
        Path(__file__).resolve().parents[1]
        / "services/agents/skills/revise-chapter/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "`count_chapter_words`" in skill
    assert "`chapter_revision_decision.txt`" in skill
    assert "`chapter_local_edit.txt`" in skill
    assert 'update_node(mode="replace"' in skill
    assert "85%" not in skill
    assert "115%" not in skill
    assert "每次任务最多两次篇幅修改" in skill


def test_removed_operational_rules_are_available_from_registered_tools():
    from services.agents.supervisor import SupervisorAgent

    tools = {tool.name: tool for tool in SupervisorAgent()._get_tools()}

    create_schema_text = str(tools["create_node"].args_schema.model_json_schema())
    assert "支持 5 种节点" in create_schema_text
    assert "chapter_elements" not in create_schema_text
    assert "storylines" in create_schema_text

    update_schema_text = str(tools["update_node"].args_schema.model_json_schema())
    update_tool_text = tools["update_node"].description + update_schema_text
    assert "content_edit_instruction" not in update_tool_text
    assert "完整正文" in update_tool_text
    assert "content_edit_instruction" not in PROMPT

    assert "write_todolist" in tools
    assert "insert_chapter_illustration" not in tools
    assert "final_report" in tools["list_research_artifacts"].description


def test_prompt_requires_brief_final_user_reply():
    assert "最终答复应短而具体" in PROMPT
    assert "章节正文和过程记录应按系统工具保存，不在消息里重复整章" in PROMPT
    assert "不要反复展示内部清单、评审过程和写作理论" in PROMPT


def test_prompt_leaves_layout_to_frontend():
    """布局由前端按可见子图自动计算，提示词不再指导 Agent 摆放坐标。"""
    assert "## 布局建议" not in PROMPT
    from node_types import NODE_LAYOUT_RULES_TEXT
    assert "前端" in NODE_LAYOUT_RULES_TEXT
    assert "画布左侧" not in NODE_LAYOUT_RULES_TEXT
    assert "不会自动重排" not in NODE_LAYOUT_RULES_TEXT
    assert "element" not in NODE_LAYOUT_RULES_TEXT


def test_prompt_explains_how_to_use_research_artifacts():
    assert "研究结论只是方法参考，而不是高于正文和设定的事实。" in PROMPT
    assert "不得把参考素材当作本作事实。" in PROMPT
    assert "旧规划和研究材料不能覆盖新正文" in PROMPT


def test_prompt_requires_active_note_maintenance():
    assert "## 长期笔记" in PROMPT
    assert "每轮自动注入的作品笔记视为当前有效的长期材料" in PROMPT
    assert "应短而完整，记录明确规则、适用范围、例外和关键因果" in PROMPT
    assert "相同主题只维持一个有效笔记节点" in PROMPT
    assert "回读" in PROMPT
    skill = (
        Path(__file__).resolve().parents[1]
        / "services/agents/skills/bootstrap-novel/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "`note`" in skill
    architect = (
        Path(__file__).resolve().parents[1]
        / "services/agents/skills/references/premise_architect.txt"
    ).read_text(encoding="utf-8")
    assert "`note`" in architect
    assert "持续生效" in architect
    assert "待办" not in architect
    assert "review_goal" in PROMPT and "author_requirements" in PROMPT


def test_prose_writing_prompts_share_chapter_writer_style_rules():
    skills = Path(__file__).resolve().parents[1] / "services/agents/skills"
    writer = (skills / "references" / "chapter_writer.txt").read_text(encoding="utf-8")
    assert writer.count("先站在角色的角度，结合其性格与当时处境") == 1
    for skill_name in ("write-chapter", "revise-chapter", "humanize-fiction"):
        skill = (skills / skill_name / "SKILL.md").read_text(encoding="utf-8")
        assert "chapter_writer.txt" in skill
        assert "read_skill_reference" in skill or "完整读取" in skill


def test_writing_prompts_require_character_pov_analysis():
    specialists = Path(__file__).resolve().parents[1] / "services/agents/skills/references"
    required = "先站在角色的角度，结合其性格与当时处境"

    scene_plan = (specialists / "scene_plan.txt").read_text(encoding="utf-8")
    assert "事件、人物目标、已知信息、选择、后果" in scene_plan
    assert "人物身份与认知范围和上下文一致" in scene_plan
    assert "具体台词、成品心理句和文学表达由正文阶段生成" in scene_plan
    writer = (specialists / "chapter_writer.txt").read_text(encoding="utf-8")
    assert required in writer
    assert "人物已知信息" in writer
    assert "叙述视角" in writer


def test_chapter_writer_treats_scene_plan_as_facts_instead_of_draft_prose():
    prompt = (
        Path(__file__).resolve().parents[1]
        / "services/agents/skills/references/chapter_writer.txt"
    ).read_text(encoding="utf-8")
    assert "任务说明提供的是事实、目标、选择、后果和信息变化" in prompt
    assert "根据现场语境独立完成具体措辞、句式、心理呈现和叙述节奏" in prompt


def test_supervisor_delegates_prose_to_writer_and_reads_back():
    assert "内容保存后用 `read_node_content` 回读整章" in PROMPT
    assert 'mode="replace"' in PROMPT
    assert 'mode="overwrite"' in PROMPT
    assert "## 第四步：交给独立 Writer" in PROMPT
    assert "compose_chapter" in PROMPT
    assert "content_sha256" in PROMPT
    assert "run_writing_agent" not in PROMPT
    assert "write_content" not in PROMPT
