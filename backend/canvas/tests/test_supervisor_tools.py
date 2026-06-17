"""Supervisor 单 Agent 收口测试 — TDD。

工具集直接挂全部操作工具（查询 + 节点 CRUD + write_chapter），
不再含 dispatch_outline/chapter/evaluation 派发工具。
"""
from app.services.agents.supervisor import SupervisorAgent


def test_supervisor_has_direct_node_ops():
    agent = SupervisorAgent()
    names = {t.name for t in agent._get_tools()}
    for required in (
        "create_node", "update_node", "delete_node",
        "create_edge", "delete_edge", "update_edge",
        "batch_create_nodes", "batch_create_edges",
        "write_chapter", "get_canvas_index",
        "query_nodes", "read_node_content",
    ):
        assert required in names, f"缺少工具: {required}"


def test_supervisor_no_dispatch_tools():
    agent = SupervisorAgent()
    names = {t.name for t in agent._get_tools()}
    for removed in (
        "dispatch_outline_agent",
        "dispatch_chapter_agent",
        "dispatch_evaluation_agent",
    ):
        assert removed not in names, f"应移除 dispatch 工具: {removed}"
