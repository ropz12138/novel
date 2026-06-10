"""Supervisor 流式思考过程：reasoning_content 提取与 SSE phase 字段。"""

import sys

from langchain_core.messages import AIMessageChunk

sys.path.insert(0, "/root/Novel/backend")

from app.services.supervisor.sub_agent_base import (
    AGENT_THINKING_EXTRA_BODY,
    chunk_to_ai_message,
    stream_reasoning_delta,
    stream_text_delta,
)
from app.services.supervisor.supervisor_agent import SUPERVISOR_THINKING_EXTRA_BODY


class TestSupervisorStreamReasoningDelta:
    def test_extracts_reasoning_content_from_chunk(self):
        chunk = AIMessageChunk(content="", additional_kwargs={"reasoning_content": "分析用户需求"})
        assert stream_reasoning_delta(chunk) == "分析用户需求"
        assert stream_text_delta(chunk) == ""

    def test_extracts_content_and_reasoning_separately(self):
        chunk = AIMessageChunk(
            content="好的",
            additional_kwargs={"reasoning_content": "先理解意图"},
        )
        assert stream_reasoning_delta(chunk) == "先理解意图"
        assert stream_text_delta(chunk) == "好的"

    def test_empty_when_no_reasoning(self):
        chunk = AIMessageChunk(content="回复")
        assert stream_reasoning_delta(chunk) == ""


class TestSupervisorThinkingExtraBody:
    def test_supervisor_enables_thinking_mode(self):
        assert SUPERVISOR_THINKING_EXTRA_BODY == AGENT_THINKING_EXTRA_BODY
        assert AGENT_THINKING_EXTRA_BODY == {"thinking": {"type": "enabled"}}


class TestChunkToAiMessagePreservesReasoning:
    def test_preserves_reasoning_content_on_aggregated_chunk(self):
        chunk = AIMessageChunk(
            content="最终回复",
            additional_kwargs={"reasoning_content": "完整推理"},
        )
        msg = chunk_to_ai_message(chunk)
        assert msg.content == "最终回复"
        assert msg.additional_kwargs.get("reasoning_content") == "完整推理"
