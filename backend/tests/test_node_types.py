"""节点类型枚举测试 — 类型收紧为 7 种。

层级链：outline(大纲) → volume(卷) → plot(情节) → chapter(章节)
全局节点：worldbuilding(世界观)、style(风格)
关联节点：character(角色) — 需与相关章节/情节等节点连接
情节元素不再作为节点类型，存放在 chapter.extra_data.chapter_elements
"""
from services.agents.tools.node_tools import VALID_NODE_TYPES


def test_valid_node_types_exactly_seven():
    assert set(VALID_NODE_TYPES) == {
        "character", "outline", "volume", "plot",
        "chapter", "worldbuilding", "style",
    }


def test_removed_types_not_allowed():
    for removed in (
        "macro_outline", "meso_outline", "micro_outline",
        "question", "constraint",
        "event", "idea", "setting", "conflict", "foreshadow",
        "theme", "core_idea", "element",
    ):
        assert removed not in VALID_NODE_TYPES


def test_element_is_not_a_node_type():
    assert "element" not in VALID_NODE_TYPES
