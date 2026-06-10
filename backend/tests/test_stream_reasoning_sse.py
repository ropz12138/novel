"""流式 reasoning + content SSE 公共 helper 测试。"""

import asyncio
import sys
from unittest.mock import MagicMock
from langchain_core.messages import AIMessageChunk

sys.path.insert(0, "/root/Novel/backend")

from app.services.supervisor.sub_agent_base import (
    emit_llm_stream_deltas,
    stream_chain_with_reasoning,
    stream_reasoning_delta,
    stream_text_delta,
)


class TestStreamDeltas:
    def test_stream_reasoning_delta(self):
        chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "分析"})
        assert stream_reasoning_delta(chunk) == "分析"
        assert stream_text_delta(chunk) == ""

    def test_stream_text_delta(self):
        chunk = AIMessageChunk(content='{"edits":')
        assert stream_text_delta(chunk) == '{"edits":'
        assert stream_reasoning_delta(chunk) == ""


class TestEmitLlmStreamDeltas:
    def test_emits_reasoning_then_content(self):
        emitted = []

        def emit(event, data):
            emitted.append((event, data))

        chunk = AIMessageChunk(
            content="正文",
            additional_kwargs={"reasoning_content": "思考"},
        )
        emit_llm_stream_deltas(emit, "edit_chapter_stream", chunk)
        assert emitted == [
            ("edit_chapter_stream", {"chunk": "思考", "phase": "reasoning"}),
            ("edit_chapter_stream", {"chunk": "正文", "phase": "content"}),
        ]

    def test_skips_empty(self):
        emitted = []
        emit_llm_stream_deltas(
            lambda e, d: emitted.append((e, d)),
            "write_stream",
            AIMessageChunk(content=""),
        )
        assert emitted == []


def test_stream_chain_with_reasoning():
    emitted = []

    async def fake_astream(_inputs):
        yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": "想"})
        yield AIMessageChunk(content='{"x":1}', additional_kwargs={"reasoning_content": ""})

    chain = MagicMock()
    chain.astream = fake_astream

    raw = asyncio.run(
        stream_chain_with_reasoning(
            chain,
            {"q": 1},
            emit=lambda e, d: emitted.append((e, d)),
            stream_event="edit_chapter_stream",
        )
    )
    assert raw == '{"x":1}'
    assert ("edit_chapter_stream", {"chunk": "想", "phase": "reasoning"}) in emitted
    assert ("edit_chapter_stream", {"chunk": '{"x":1}', "phase": "content"}) in emitted
