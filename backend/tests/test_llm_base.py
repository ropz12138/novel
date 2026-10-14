"""LLM 协议基类：OpenAI SSE 解析、主备切换。"""
import asyncio
import logging

import pytest

from services.llm.llm_service import BaseLLMProvider, OpenAILLMClient
from services.llm.llm_tool import ToolStreamEvent
from services.llm.llm_types import LLMModelConfig


def _cfg(name: str = "m") -> LLMModelConfig:
    return LLMModelConfig(
        name=name,
        base_url="http://example.test/v1",
        api_key="k",
        provider="openai",
        model=name,
    )


class _FakeStreamResponse:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code
        self.is_success = status_code < 400
        self.request = type("Req", (), {"url": "http://example.test/v1/chat/completions"})()

    async def aread(self):
        return b"err"

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class _FakeAsyncClient:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self._status_code = status_code
        self.closed = False

    def stream(self, *args, **kwargs):
        return _FakeStreamResponse(self._lines, self._status_code)

    async def aclose(self):
        self.closed = True


class _FakeProtocolClient:
    def __init__(self, events=None, exc=None):
        self.events = list(events or [])
        self.exc = exc
        self.calls = 0

    async def stream_chat(self, messages, *, client=None, tools=None, raw_event_hook=None, tool_choice=None):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        for event in self.events:
            yield event

    def complete(self, messages, **kwargs):
        if self.exc is not None:
            raise self.exc
        return "ok"

    async def acomplete(self, messages, **kwargs):
        if self.exc is not None:
            raise self.exc
        return "ok"


def test_openai_client_parses_text_and_reasoning_sse():
    async def _run():
        lines = [
            'data: {"choices":[{"delta":{"reasoning_content":"想"}}]}',
            'data: {"choices":[{"delta":{"content":"你好"}}]}',
            "data: [DONE]",
        ]
        client = OpenAILLMClient(_cfg())
        events = [
            ev
            async for ev in client.stream_chat(
                [{"role": "user", "content": "hi"}],
                client=_FakeAsyncClient(lines),
            )
        ]
        assert [(ev.kind, ev.text) for ev in events] == [
            ("thinking", "想"),
            ("text", "你好"),
        ]

    asyncio.run(_run())


def test_openai_client_emits_terminal_usage_event():
    async def _run():
        lines = [
            'data: {"choices":[{"delta":{"content":"好"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":13,"completion_tokens":3,"total_tokens":16}}',
            "data: [DONE]",
        ]
        client = OpenAILLMClient(_cfg())
        return [
            ev async for ev in client.stream_chat(
                [{"role": "user", "content": "hi"}],
                client=_FakeAsyncClient(lines),
            )
        ]

    events = asyncio.run(_run())
    assert events[-1].kind == "usage"
    assert events[-1].usage == {
        "input_tokens": 13,
        "output_tokens": 3,
        "total_tokens": 16,
    }


def test_openai_client_assembles_tool_call_from_fragments():
    async def _run():
        lines = [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"query_nodes","arguments":"{\\"a\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"1}"}}]},"finish_reason":"tool_calls"}]}',
            "data: [DONE]",
        ]
        client = OpenAILLMClient(_cfg())
        events = [
            ev
            async for ev in client.stream_chat(
                [{"role": "user", "content": "hi"}],
                client=_FakeAsyncClient(lines),
            )
        ]
        tool_events = [ev for ev in events if ev.kind == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0].tool_call.tool_name == "query_nodes"
        assert tool_events[0].tool_call.call_id == "c1"
        assert tool_events[0].tool_call.arguments == {"a": 1}

    asyncio.run(_run())


def test_base_provider_logs_full_thinking(caplog):
    async def _run():
        primary = _FakeProtocolClient(events=[
            ToolStreamEvent(kind="thinking", text="The user wants "),
            ToolStreamEvent(kind="thinking", text="to look at the first chapter."),
            ToolStreamEvent(kind="text", text="ok"),
        ])
        provider = BaseLLMProvider(_cfg("glm-5.3-flash"), _client=primary)
        with caplog.at_level(logging.INFO, logger="llm"):
            events = [
                ev
                async for ev in provider.stream_chat([{"role": "user", "content": "hi"}])
            ]
        assert [(ev.kind, ev.text) for ev in events] == [
            ("thinking", "The user wants "),
            ("thinking", "to look at the first chapter."),
            ("text", "ok"),
        ]
        thinking_logs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("LLM thinking")]
        assert thinking_logs == [
            "LLM thinking [glm-5.3-flash] The user wants to look at the first chapter.",
        ]

    asyncio.run(_run())


def test_base_provider_logs_thinking_when_stream_ends_on_thinking(caplog):
    async def _run():
        primary = _FakeProtocolClient(events=[
            ToolStreamEvent(kind="thinking", text="只思考"),
        ])
        provider = BaseLLMProvider(_cfg("glm-5.3-flash"), _client=primary)
        with caplog.at_level(logging.INFO, logger="llm"):
            async for _ev in provider.stream_chat([{"role": "user", "content": "hi"}]):
                pass
        thinking_logs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("LLM thinking")]
        assert thinking_logs == ["LLM thinking [glm-5.3-flash] 只思考"]

    asyncio.run(_run())


def test_base_provider_falls_back_on_stream_error():
    async def _run():
        primary = _FakeProtocolClient(exc=RuntimeError("primary down"))
        fallback = _FakeProtocolClient(events=[ToolStreamEvent(kind="text", text="备")])
        provider = BaseLLMProvider(
            _cfg("p"),
            _cfg("f"),
            _client=primary,
            _fallback_client=fallback,
        )
        texts = [
            ev.text
            async for ev in provider.stream_chat([{"role": "user", "content": "x"}])
            if ev.kind == "text"
        ]
        assert texts == ["备"]
        assert primary.calls == 1
        assert fallback.calls == 1

    asyncio.run(_run())


def test_base_provider_hides_llm_error_details_without_fallback():
    async def _run():
        provider = BaseLLMProvider(
            _cfg("gemini"),
            _client=_FakeProtocolClient(exc=RuntimeError("secret gateway body")),
        )
        with pytest.raises(RuntimeError) as caught:
            async for _event in provider.stream_chat([{"role": "user", "content": "hi"}]):
                pass
        assert str(caught.value) == "AI额度不足，请稍后再试"
        assert "secret gateway body" not in str(caught.value)

    asyncio.run(_run())


def test_base_provider_hides_complete_error_details_without_fallback():
    provider = BaseLLMProvider(
        _cfg("gemini"),
        _client=_FakeProtocolClient(exc=RuntimeError("secret gateway body")),
    )
    with pytest.raises(RuntimeError, match="^AI额度不足，请稍后再试$"):
        provider.complete([{"role": "user", "content": "hi"}])
