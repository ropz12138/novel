"""Supervisor 章节工作流提示词测试。"""
from pathlib import Path


PROMPT = (
    Path(__file__).resolve().parents[1]
    / "services/agents/prompts/supervisor_system.txt"
).read_text(encoding="utf-8")


def test_prompt_states_markdown_for_non_chapter_content_and_chapter_notes():
    assert "非章节节点正文和章节笔记使用 Markdown 格式组织内容，按需要采用标题、列表与自然段；章节正文保持小说正文格式。" in PROMPT
    assert "局部修改使用工具返回的 content_paragraphs 或 notes_paragraphs 中的 number 选择范围，new 保留选中内容所需的 Markdown 标记与缩进。" in PROMPT
    assert "小说正文必须输出 Markdown" not in PROMPT


def test_prompt_limits_node_types():
    for node_type in ("character", "outline", "volume", "plot", "chapter", "worldbuilding", "note"):
        assert f"`{node_type}`" in PROMPT
    assert "`note`" in PROMPT
    assert "`style`" not in PROMPT
    assert "持续生效" in PROMPT
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
    assert "read_todolist" in PROMPT
    assert "update_todolist" in PROMPT
    assert "章节正文以 3000 字为目标" not in PROMPT
    assert "2500–3500 字" not in PROMPT
    assert "`write_chapter`" not in PROMPT
    assert "`edit_chapter_content`" not in PROMPT
    assert "新章用 `create_node`" in PROMPT
    assert "所属 plot" in PROMPT
    assert "`chapter_elements`" in PROMPT
    assert "`save_chapter_notes`" in PROMPT
    assert "`save_workflow_record`" not in PROMPT
    assert "`read_workflow_records`" not in PROMPT


def test_prompt_limits_word_count_adjustment_to_two_attempts():
    assert "默认 2000 字左右" in PROMPT
    assert "新写和整章重写按该篇幅组织正文" in PROMPT
    assert "局部修改保持本章既有篇幅" in PROMPT
    assert "针对字数的调整，每次执行最多两次" in PROMPT
    assert "达到次数后说明当前字数与目标差距" in PROMPT
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
    assert "## 需求分析与方案选择" in PROMPT
    assert "先提炼用户真正想获得的结果" in PROMPT
    assert "提供 2—3 个可执行方案" in PROMPT
    assert "明确推荐其中一个方案" in PROMPT
    assert "等待用户选择后执行" in PROMPT
    assert "执行路径已经明确" in PROMPT


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
    assert "element 不再是节点类型" in create_schema_text
    assert "chapter_elements" in create_schema_text
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
    assert "给用户的最终回答必须简略" in PROMPT
    assert "控制在几句话以内" in PROMPT
    assert "正文与过程记录通过工具保存" in PROMPT
    assert "场景规划" in PROMPT
    assert "评审证据" in PROMPT


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
    assert "当前作品的角色、设定和正文是创作事实依据" in PROMPT


def test_prompt_requires_active_note_maintenance():
    assert "## 笔记维护" in PROMPT
    assert "自动完整注入" in PROMPT
    assert "完整可执行条目" in PROMPT
    assert "同一主题只维护一个笔记节点" in PROMPT
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


def test_supervisor_writes_chapters_directly_and_reads_back():
    assert "必须调用 `read_node_content` 重新读取已保存的整章正文" in PROMPT
    assert 'mode="replace"' in PROMPT
    assert 'mode="overwrite"' in PROMPT
    assert "你直接负责章节正文的创作与修订" in PROMPT
    assert "content_sha256" in PROMPT
    assert "run_writing_agent" not in PROMPT
    assert "write_content" not in PROMPT
