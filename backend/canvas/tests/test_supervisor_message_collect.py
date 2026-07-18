"""graph.astream 消息累积测试。"""
from langchain_core.messages import AIMessage, ToolMessage

from app.services.agents.supervisor import _collect_messages_from_graph_event


def test_collect_appends_agent_messages():
    msgs = _collect_messages_from_graph_event(
        [],
        "agent",
        {"messages": [AIMessage(content="你好")]},
    )
    assert len(msgs) == 1
    assert msgs[0].content == "你好"


def test_collect_appends_tools_messages():
    base = [AIMessage(content="调用", tool_calls=[{"name": "get_canvas_index", "args": {}, "id": "c1"}])]
    msgs = _collect_messages_from_graph_event(
        base,
        "tools",
        {"messages": [ToolMessage(content="ok", tool_call_id="c1", name="get_canvas_index")]},
    )
    assert len(msgs) == 2
    assert isinstance(msgs[1], ToolMessage)


def test_collect_ignores_unknown_nodes():
    base = [AIMessage(content="x")]
    msgs = _collect_messages_from_graph_event(base, "other", {"messages": [AIMessage(content="y")]})
    assert len(msgs) == 1
