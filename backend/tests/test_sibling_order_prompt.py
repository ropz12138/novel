"""同级顺序与同级连线的提示词约定 — TDD

顺序改由 sort_order 字段表达后，Agent 必须同时知道两件事：
  - 创建节点要给 sort_order；
  - 同级之间不要连线（否则它会反复尝试各种 edge_type 表达顺序）。
"""
import importlib
from pathlib import Path

from node_types import (
    EDGE_CONNECTION_RULES_TEXT,
    EDGE_ENDPOINT_RULES_TEXT,
    MISSING_SORT_ORDER_ERROR,
    NODE_LAYOUT_RULES_TEXT,
    NODE_SORT_ORDER_RULES_TEXT,
)

nt = importlib.import_module("services.agents.tools.node_tools")

PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "services" / "agents" / "prompts" / "supervisor_system.txt"
)


def test_sort_order_rules_text_explains_ordering():
    assert "sort_order" in NODE_SORT_ORDER_RULES_TEXT
    assert "同级" in NODE_SORT_ORDER_RULES_TEXT


def test_endpoint_rules_forbid_same_level_edges():
    assert "同级" in EDGE_ENDPOINT_RULES_TEXT
    assert "sort_order" in EDGE_ENDPOINT_RULES_TEXT


def test_connection_rules_drop_chapter_to_chapter():
    """chapter↔chapter 端点规则已随同级连线一并移除，留着会诱导 Agent 建同级边。"""
    assert "chapter↔chapter" not in EDGE_CONNECTION_RULES_TEXT


def test_layout_rules_mention_sort_order_for_horizontal_order():
    assert "sort_order" in NODE_LAYOUT_RULES_TEXT


def test_missing_sort_order_error_is_actionable():
    assert "sort_order" in MISSING_SORT_ORDER_ERROR


def test_supervisor_prompt_states_sort_order_and_forbids_same_level_edges():
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    assert "sort_order" in prompt
    assert "同级之间禁止连线" in prompt


def test_create_node_tool_description_requires_sort_order():
    assert "sort_order" in nt.create_node.description


def test_batch_create_nodes_tool_description_requires_sort_order():
    assert "sort_order" in nt.batch_create_nodes.description


def test_create_edge_tool_description_forbids_same_level():
    assert "同级" in nt.create_edge.description
