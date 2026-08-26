"""tool_result_utils 单元测试。"""
from langchain_core.messages import AIMessage, ToolMessage

from services.tool_result_utils import (
    lookup_tool_results_after,
    tool_message_success,
)


def test_tool_message_success_plain_text():
    assert tool_message_success("操作完成") is True


def test_tool_message_success_error_keyword():
    assert tool_message_success("失败：节点不存在") is False


def test_tool_message_success_json_error_field():
    assert tool_message_success('{"error": "not found"}') is False


def test_tool_message_success_json_success_false():
    assert tool_message_success('{"success": false}') is False


def test_tool_message_success_json_ok():
    assert tool_message_success('{"ok": true}') is True


def test_lookup_tool_results_after():
    ai = AIMessage(
        content="",
        tool_calls=[{"id": "call_1", "name": "get_canvas_index", "args": {}}],
    )
    tool = ToolMessage(content='{"nodes": []}', tool_call_id="call_1", name="get_canvas_index")
    final = AIMessage(content="完成")
    messages = [ai, tool, final]

    results = lookup_tool_results_after(messages, 1)
    assert "call_1" in results
    assert results["get_canvas_index"] is tool
