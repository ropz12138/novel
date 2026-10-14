import asyncio

from langchain_core.messages import AIMessageChunk

from services.agents.supervisor import (
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
                yield AIMessageChunk(
                    content="",
                    tool_calls=[{
                        "name": "respond_to_user",
                        "args": {"message": "recovered"},
                        "id": "call_end",
                        "type": "tool_call",
                    }],
                )

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


def test_direct_writing_retry_keeps_all_calls_and_full_long_draft():
    calls = [{
        "name": "update_node", "id": f"bad_{i}",
        "args": '{"content": "' + "长篇正文" * 4000 + f'第{i}章结尾"}}]',
    } for i in range(4)]
    message = AIMessageChunk(content="", invalid_tool_calls=calls)
    feedback = _build_tool_call_parse_feedback(message)
    for call in calls:
        assert call["id"] in feedback
        assert call["args"] in feedback
    assert "args truncated" not in feedback
