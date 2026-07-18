"""Supervisor stage_start 事件测试 — TDD。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessageChunk

from app.services.agents.supervisor import SupervisorAgent


class _FakeLLM:
    def bind_tools(self, tools, **kwargs):
        return self

    def astream(self, messages):
        async def _gen():
            yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": "思考"})
            yield AIMessageChunk(content="完成")
        return _gen()


def test_agent_node_emits_stage_start_before_stream(monkeypatch):
    emitted = []

    async def capture(event, data):
        emitted.append((event, data))

    monkeypatch.setattr(
        "app.services.agents.supervisor.get_llm",
        lambda **kw: _FakeLLM(),
    )
    monkeypatch.setattr(
        "app.services.agents.supervisor.bind_tools_to_llm",
        lambda llm, tools: llm,
    )

    agent = SupervisorAgent(emit=capture)
    graph = agent._build_graph()
    state = {
        "messages": [],
        "user_message": "你好",
        "canvas_overview": "",
    }

    async def _run():
        result = None
        async for event in graph.astream(state):
            if "agent" in event:
                result = event["agent"]
        return result

    asyncio.run(_run())

    stage_events = [e for e in emitted if e[0] == "stage_start"]
    assert len(stage_events) >= 1
    assert stage_events[0][1]["stage"] == "thinking"
    assert stage_events[0][1]["label"] == "AI 思考中"

    stream_events = [e for e in emitted if e[0] == "supervisor_stream"]
    assert any(e[1].get("phase") == "reasoning" for e in stream_events)
