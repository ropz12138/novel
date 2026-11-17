"""仅支持章节、角色、世界观、笔记、评审笔记五类节点。"""
from services.agents.tools.node_tools import VALID_NODE_TYPES


def test_valid_node_types_include_dedicated_reviewer_note():
    assert set(VALID_NODE_TYPES) == {
        "character",
        "chapter", "worldbuilding", "note", "reviewer_note",
    }


def test_removed_types_not_allowed():
    for removed in (
        "outline", "volume", "plot", "macro_outline", "meso_outline", "micro_outline",
        "question", "constraint",
        "event", "idea", "setting", "conflict", "foreshadow",
        "theme", "core_idea", "element", "style",
    ):
        assert removed not in VALID_NODE_TYPES


def test_element_is_not_a_node_type():
    assert "element" not in VALID_NODE_TYPES
