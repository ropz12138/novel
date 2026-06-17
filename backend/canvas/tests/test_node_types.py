"""节点类型枚举测试 — TDD：驱动类型枚举精简为 10 种。

去掉三纲（macro/meso/micro_outline）合并为 outline，去掉 question/constraint。
"""
from app.services.agents.tools.node_tools import VALID_NODE_TYPES


def test_valid_node_types_exactly_ten():
    assert set(VALID_NODE_TYPES) == {
        "idea", "outline", "chapter", "character", "style",
        "conflict", "foreshadow", "theme", "worldbuilding", "event",
    }


def test_three_outline_types_removed():
    for removed in (
        "macro_outline", "meso_outline", "micro_outline",
        "question", "constraint",
    ):
        assert removed not in VALID_NODE_TYPES
