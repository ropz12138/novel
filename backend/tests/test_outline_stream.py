"""Tests for outline generation streaming via _invoke_and_persist."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import AIMessageChunk


def _make_chunk(content="", tool_call_chunks=None):
    """Create a minimal AIMessageChunk for testing."""
    kwargs = {"content": content}
    if tool_call_chunks is not None:
        kwargs["tool_call_chunks"] = tool_call_chunks
    return AIMessageChunk(**kwargs)


class AsyncIterator:
    """Helper to make an async iterator from a list."""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


class TestInvokeAndPersistStreaming:
    """Verify _invoke_and_persist calls emit_fn for each LLM chunk."""

    @pytest.mark.asyncio
    async def test_emits_stream_deltas_when_emit_fn_provided(self):
        from app.services.supervisor.outline_tools import _invoke_and_persist

        captured_events = []

        def fake_emit(event, data):
            captured_events.append((event, data))

        chunk1 = _make_chunk(content="thinking...")
        chunk2 = AIMessageChunk(
            content="",
            tool_call_chunks=[{
                "name": "submit_macro_outline",
                "args": '{"macro_phases": []}',
                "id": "tc1",
                "index": 0,
            }],
        )

        mock_llm_instance = MagicMock()
        # astream must return an async iterable directly (not a coroutine)
        mock_llm_instance.astream.return_value = AsyncIterator([chunk1, chunk2])
        mock_llm_instance.bind_tools.return_value = mock_llm_instance

        mock_submit_tool = MagicMock(spec=[])
        mock_submit_tool.name = "submit_macro_outline"
        mock_submit_tool.func = MagicMock()

        with patch("app.services.supervisor.sub_agent_base.get_llm", return_value=mock_llm_instance), \
             patch("app.services.supervisor.sub_agent_base.chunk_to_ai_message") as mock_chunk_to_msg, \
             patch("app.services.supervisor.outline_tools._extract_tool_call_args") as mock_extract:
            mock_chunk_to_msg.return_value = MagicMock()
            mock_extract.return_value = {"macro_phases": []}

            result = await _invoke_and_persist(
                prompt="test prompt",
                submit_tool=mock_submit_tool,
                tool_name="submit_macro_outline",
                emit_fn=fake_emit,
            )

        stream_events = [e for e in captured_events if e[0] == "outline_stream"]
        assert len(stream_events) >= 1, f"Expected outline_stream events, got {captured_events}"
        content_events = [e for e in stream_events if e[1].get("phase") == "content"]
        assert any("thinking" in e[1].get("chunk", "") for e in content_events)

    @pytest.mark.asyncio
    async def test_no_emission_when_emit_fn_is_none(self):
        from app.services.supervisor.outline_tools import _invoke_and_persist

        chunk = _make_chunk(content="test")

        mock_llm_instance = MagicMock()
        mock_llm_instance.astream.return_value = AsyncIterator([chunk])
        mock_llm_instance.bind_tools.return_value = mock_llm_instance

        mock_submit_tool = MagicMock(spec=[])
        mock_submit_tool.name = "submit_macro_outline"
        mock_submit_tool.func = MagicMock()

        with patch("app.services.supervisor.sub_agent_base.get_llm", return_value=mock_llm_instance), \
             patch("app.services.supervisor.sub_agent_base.chunk_to_ai_message") as mock_chunk_to_msg, \
             patch("app.services.supervisor.outline_tools._extract_tool_call_args") as mock_extract:
            mock_chunk_to_msg.return_value = MagicMock()
            mock_extract.return_value = {"macro_phases": []}

            result = await _invoke_and_persist(
                prompt="test prompt",
                submit_tool=mock_submit_tool,
                tool_name="submit_macro_outline",
                emit_fn=None,
            )

        assert result == {"macro_phases": []}

    @pytest.mark.asyncio
    async def test_uses_custom_stream_event_name(self):
        from app.services.supervisor.outline_tools import _invoke_and_persist

        captured_events = []

        def fake_emit(event, data):
            captured_events.append((event, data))

        chunk = _make_chunk(content="data")

        mock_llm_instance = MagicMock()
        mock_llm_instance.astream.return_value = AsyncIterator([chunk])
        mock_llm_instance.bind_tools.return_value = mock_llm_instance

        mock_submit_tool = MagicMock(spec=[])
        mock_submit_tool.name = "submit_meso_outline"
        mock_submit_tool.func = MagicMock()

        with patch("app.services.supervisor.sub_agent_base.get_llm", return_value=mock_llm_instance), \
             patch("app.services.supervisor.sub_agent_base.chunk_to_ai_message") as mock_chunk_to_msg, \
             patch("app.services.supervisor.outline_tools._extract_tool_call_args") as mock_extract:
            mock_chunk_to_msg.return_value = MagicMock()
            mock_extract.return_value = {"meso_stages": []}

            result = await _invoke_and_persist(
                prompt="test prompt",
                submit_tool=mock_submit_tool,
                tool_name="submit_meso_outline",
                field_name="meso_stages",
                stream_event="custom_event",
                emit_fn=fake_emit,
            )

        custom_events = [e for e in captured_events if e[0] == "custom_event"]
        assert len(custom_events) >= 1, f"Expected custom_event, got {captured_events}"


class TestFrontendOutlineStreamSource:
    """Verify _invoke_and_persist code has streaming support."""

    def test_function_accepts_emit_fn(self):
        import inspect
        from app.services.supervisor.outline_tools import _invoke_and_persist

        sig = inspect.signature(_invoke_and_persist)
        assert "emit_fn" in sig.parameters
        assert "stream_event" in sig.parameters

    def test_function_uses_astream(self):
        import inspect
        from app.services.supervisor.outline_tools import _invoke_and_persist

        source = inspect.getsource(_invoke_and_persist)
        assert "astream" in source
        assert "emit_llm_stream_deltas" in source
