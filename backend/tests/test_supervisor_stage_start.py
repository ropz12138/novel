"""Supervisor stage_start 事件测试 — TDD。"""
import asyncio
from langchain_core.messages import AIMessage, AIMessageChunk

from services.agents.supervisor import SupervisorAgent


class _FakeGraph:
    async def astream(self, state, config=None, stream_mode=None):
        yield "messages", (
            AIMessageChunk(content="", additional_kwargs={"reasoning_content": "思考"}),
            {"langgraph_node": "model"},
        )
        yield "updates", {"model": {"messages": [AIMessage(content="完成")]}}


def test_agent_node_emits_stage_start_before_stream(monkeypatch):
    emitted = []

    async def capture(event, data):
        emitted.append((event, data))

    agent = SupervisorAgent(emit=capture)
    monkeypatch.setattr(agent, "_build_graph", lambda **kwargs: _FakeGraph())
    result = asyncio.run(agent.run("你好", context={}))
    assert result["message"] == "完成"

    stage_events = [e for e in emitted if e[0] == "stage_start"]
    assert len(stage_events) >= 1
    assert stage_events[0][1]["stage"] == "thinking"
    assert stage_events[0][1]["label"] == "AI 思考中"

    stream_events = [e for e in emitted if e[0] == "supervisor_stream"]
    assert any(e[1].get("phase") == "reasoning" for e in stream_events)
