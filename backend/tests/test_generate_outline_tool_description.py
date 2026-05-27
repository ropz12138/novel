"""generate_outline 工具描述应明确告知 Agent 一次调用会生成并入库的全部内容。"""


def test_generate_outline_description_lists_all_generated_sections():
    from app.services.supervisor.outline_tools import generate_outline

    desc = generate_outline.description or ""
    for keyword in (
        "角色",
        "timeline",
        "支线",
        "伏笔",
        "character_links",
        "作品",
    ):
        assert keyword in desc, f"description 应包含「{keyword}」"


def test_generate_outline_description_forbids_natural_language_character_cards():
    from app.services.supervisor.outline_tools import generate_outline

    desc = generate_outline.description or ""
    assert "不要" in desc or "禁止" in desc
    assert "自然语言" in desc or "文本" in desc


def test_generate_outline_idea_field_mentions_user_constraints():
    from app.services.supervisor.outline_tools import GenerateOutlineInput

    idea_field = GenerateOutlineInput.model_fields["idea"]
    assert idea_field.description
    assert "约束" in idea_field.description or "数量" in idea_field.description
