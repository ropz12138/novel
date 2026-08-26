"""LLM 流式增量解析测试。"""
import asyncio

from langchain_core.messages import AIMessageChunk

from services.llm_stream import (
    emit_llm_stream_deltas,
    stream_reasoning_delta,
    stream_text_delta,
)


def test_stream_text_delta_from_string():
    chunk = AIMessageChunk(content="你好")
    assert stream_text_delta(chunk) == "你好"


def test_stream_text_delta_from_content_blocks():
    chunk = AIMessageChunk(content=[
        {"type": "text", "text": "让我先查看"},
        {"type": "tool_call", "name": "get_canvas_index", "args": {}},
    ])
    assert stream_text_delta(chunk) == "让我先查看"


def test_stream_reasoning_delta():
    chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "分析中"})
    assert stream_reasoning_delta(chunk) == "分析中"


def test_emit_llm_stream_deltas_order():
    events = []

    async def emit(event, data):
        events.append((event, data))

    chunk = AIMessageChunk(
        content="正文",
        additional_kwargs={"reasoning_content": "思考"},
    )
    asyncio.run(emit_llm_stream_deltas(emit, "supervisor_stream", chunk))
    assert len(events) == 2
    assert events[0][1]["phase"] == "reasoning"
    assert events[0][1]["chunk"] == "思考"
    assert events[1][1]["phase"] == "content"
    assert events[1][1]["chunk"] == "正文"
