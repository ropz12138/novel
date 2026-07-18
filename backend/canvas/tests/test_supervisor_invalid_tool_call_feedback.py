import asyncio

from langchain_core.messages import AIMessageChunk

from app.services.agents.supervisor import (
    SupervisorAgent,
    _build_tool_call_parse_feedback,
    _json_error_details,
)


class _RetryLLM:
    def __init__(self):
        self.calls = []

    def astream(self, messages):
        self.calls.append(messages)

        async def _gen():
            if len(self.calls) == 1:
                yield AIMessageChunk(
                    content="",
                    invalid_tool_calls=[
                        {
                            "name": "batch_create_nodes",
                            "id": "call_bad",
                            "args": '{"nodes_data": [{"content": "abc"}]}]',
                        }
                    ],
                    response_metadata={"finish_reason": "tool_calls"},
                )
            else:
                yield AIMessageChunk(content="recovered")

        return _gen()


def test_json_error_details_includes_decode_position():
    details = _json_error_details('{"nodes_data": [{"content": "abc"}]}')
    assert details["valid_json"] is True

    details = _json_error_details('{"nodes_data": [{"content": "abc"}]}]')
    assert details["valid_json"] is False
    assert details["message"]
    assert details["line"] == 1
    assert isinstance(details["column"], int)
    assert isinstance(details["position"], int)
    assert "abc" in details["context"]


def test_tool_call_parse_feedback_includes_invalid_args_and_error_location():
    msg = AIMessageChunk(
        content="",
        invalid_tool_calls=[
            {
                "name": "batch_create_nodes",
                "id": "call_bad",
                "args": '{"nodes_data": [{"content": "声称女性幸存者应被"集中保护"。"}]}',
            }
        ],
        response_metadata={"finish_reason": "tool_calls"},
    )

    feedback = _build_tool_call_parse_feedback(msg)

    assert "batch_create_nodes" in feedback
    assert "call_bad" in feedback
    assert "JSONDecodeError" in feedback
    assert "line:" in feedback
    assert "column:" in feedback
    assert "position:" in feedback
    assert "集中保护" in feedback
    assert "只重新调用工具" in feedback


def test_agent_retries_after_invalid_tool_call_json(monkeypatch):
    llm = _RetryLLM()
    monkeypatch.setattr("app.services.agents.supervisor.get_llm", lambda **kw: llm)
    monkeypatch.setattr("app.services.agents.supervisor.bind_tools_to_llm", lambda model, tools: model)

    agent = SupervisorAgent()
    graph = agent._build_graph()

    async def _run():
        result = None
        async for event in graph.astream({"messages": [], "user_message": "hi"}):
            if "agent" in event:
                result = event["agent"]
        return result

    result = asyncio.run(_run())

    assert len(llm.calls) == 2
    assert result["messages"][0].content == "recovered"
    retry_messages = llm.calls[1]
    assert "JSONDecodeError" in retry_messages[-1].content
    assert "batch_create_nodes" in retry_messages[-1].content
