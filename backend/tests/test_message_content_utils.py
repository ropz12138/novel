"""AIMessage content blocks 解析测试。"""
from langchain_core.messages import AIMessage

from services.message_content_utils import extract_text_content, extract_tool_calls


def test_extract_text_from_string():
    assert extract_text_content("你好") == "你好"


def test_extract_text_from_content_blocks():
    content = [
        {"type": "text", "text": "让我先查看一下画布的当前状态："},
        {
            "type": "tool_call",
            "id": "call_abc",
            "name": "get_canvas_index",
            "args": {"reason": "查看画布"},
        },
    ]
    assert extract_text_content(content) == "让我先查看一下画布的当前状态："


def test_extract_tool_calls_from_content_blocks():
    msg = AIMessage(content=[
        {"type": "text", "text": "让我先查看一下画布的当前状态："},
        {
            "type": "tool_call",
            "id": "call_abc",
            "name": "get_canvas_index",
            "args": {"reason": "查看画布"},
        },
    ])
    calls = extract_tool_calls(msg)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_canvas_index"
    assert calls[0]["id"] == "call_abc"


def test_extract_tool_calls_from_tool_calls_attribute():
    msg = AIMessage(
        content="调用工具",
        tool_calls=[{"id": "call_1", "name": "query_nodes", "args": {}}],
    )
    calls = extract_tool_calls(msg)
    assert len(calls) == 1
    assert calls[0]["name"] == "query_nodes"
