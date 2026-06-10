"""各 Agent 节点 reasoning 流式推送测试。"""

import asyncio
import sys
from unittest.mock import MagicMock

from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage

sys.path.insert(0, "/root/Novel/backend")

from app.services.supervisor.sub_agent_base import (
    AGENT_THINKING_EXTRA_BODY,
    astream_agent_llm_to_message,
    bind_agent_llm_with_tools,
)


class TestAgentThinkingExtraBody:
    def test_enables_thinking_mode(self):
        assert AGENT_THINKING_EXTRA_BODY == {"thinking": {"type": "enabled"}}


class TestBindAgentLlmWithTools:
    def test_passes_thinking_enabled_extra_body(self):
        llm = MagicMock()
        tools = [MagicMock()]
        bind_agent_llm_with_tools(llm, tools)
        llm.bind_tools.assert_called_once_with(tools, extra_body=AGENT_THINKING_EXTRA_BODY)


class TestAstreamAgentLlmToMessage:
    def test_emits_reasoning_and_content_then_returns_message(self):
        emitted = []

        async def fake_astream(_messages):
            yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": "规划"})
            yield AIMessageChunk(content="调用工具")

        llm = MagicMock()
        llm.astream = fake_astream

        msg = asyncio.run(
            astream_agent_llm_to_message(
                llm,
                [SystemMessage(content="sys"), HumanMessage(content="hi")],
                emit=lambda e, d: emitted.append((e, d)),
                stream_event="write_stream",
            )
        )

        assert msg.content == "调用工具"
        assert emitted == [
            ("write_stream", {"chunk": "规划", "phase": "reasoning"}),
            ("write_stream", {"chunk": "调用工具", "phase": "content"}),
        ]

    def test_skips_emit_when_callback_missing(self):
        async def fake_astream(_messages):
            yield AIMessageChunk(content="ok")

        llm = MagicMock()
        llm.astream = fake_astream

        msg = asyncio.run(
            astream_agent_llm_to_message(llm, [HumanMessage(content="hi")])
        )
        assert msg.content == "ok"
