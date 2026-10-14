import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from services.agents.deep_agent_runtime import (
    DEEP_AGENT_FORBIDDEN_TOOLS,
    build_context_backend,
    build_deep_agent,
    load_summarization_state,
    save_summarization_state,
)
from services.agents.supervisor import SupervisorAgent
from services.llm.langchain_adapter import DeepAgentChatModel
from services.llm.llm_tool import ToolStreamEvent
from services.llm.llm_types import LLMModelConfig


@tool
def allowed_tool(text: str) -> str:
    """Return the provided text."""
    return text


class FakeProvider:
    def __init__(self):
        self.config = LLMModelConfig(
            name="test-model",
            base_url="http://example.test",
            api_key="test-key",
            provider="openai",
            model="test-model",
        )
        self.fallback_config = None
        self.bound_tools = None

    async def stream_chat(self, messages, *, client=None, tools=None, raw_event_hook=None, tool_choice=None):
        self.bound_tools = tools
        yield ToolStreamEvent(kind="text", text="ok")


class SupervisorProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def stream_chat(self, messages, *, client=None, tools=None, raw_event_hook=None, tool_choice=None):
        self.calls += 1
        self.bound_tools = tools
        if messages[-1]["role"] == "tool":
            yield ToolStreamEvent(kind="text", text="已完成")
            return
        from services.llm.llm_tool import ToolCallFinished

        yield ToolStreamEvent(
            kind="tool_call",
            tool_call=ToolCallFinished(
                tool_name="respond_to_user",
                call_id="respond-1",
                arguments={"message": "已完成"},
            ),
        )


class MissingToolThenFinishProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.seen = []

    async def stream_chat(self, messages, *, client=None, tools=None, raw_event_hook=None, tool_choice=None):
        from services.llm.llm_tool import ToolCallFinished

        self.calls += 1
        self.seen.append(messages)
        if self.calls == 1:
            yield ToolStreamEvent(kind="text", text="任务已经完成")
            return
        yield ToolStreamEvent(
            kind="tool_call",
            tool_call=ToolCallFinished(
                tool_name="respond_to_user",
                call_id="respond-after-repair",
                arguments={"message": "任务已经完成"},
            ),
        )


def test_deep_agent_model_is_base_chat_model_and_uses_project_provider():
    provider = FakeProvider()
    model = DeepAgentChatModel(provider=provider, model_name="test-model")

    assert isinstance(model, BaseChatModel)
    result = asyncio.run(model.ainvoke([HumanMessage(content="hello")]))
    assert result.content == "ok"


def test_context_backend_is_persistent_and_isolated_by_business_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.agents.deep_agent_runtime.DEEP_AGENT_CONTEXT_ROOT",
        tmp_path,
    )

    first = build_context_backend("session", "session-a")
    second = build_context_backend("session", "session-b")

    assert first.cwd == (tmp_path / "session" / "session-a").resolve()
    assert second.cwd == (tmp_path / "session" / "session-b").resolve()
    assert first.virtual_mode is True
    assert second.virtual_mode is True


def test_summarization_state_round_trips_by_business_session(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.agents.deep_agent_runtime.DEEP_AGENT_CONTEXT_ROOT",
        tmp_path,
    )
    update = {
        "_summarization_event": {
            "cutoff_index": 3,
            "summary_message": HumanMessage(
                content="SESSION SUMMARY",
                additional_kwargs={"lc_source": "summarization"},
            ),
            "file_path": "/conversation_history/session_a.md",
        },
        "_summarization_session_id": "session_a",
    }

    save_summarization_state("session", "a", update)

    restored = load_summarization_state("session", "a")
    assert restored["_summarization_event"]["cutoff_index"] == 3
    assert restored["_summarization_event"]["summary_message"].content == "SESSION SUMMARY"
    assert restored["_summarization_session_id"] == "session_a"
    assert load_summarization_state("session", "b") == {}


def test_deep_agent_exposes_only_paginated_file_reader_from_builtin_file_tools():
    provider = FakeProvider()
    model = DeepAgentChatModel(provider=provider, model_name="test-model")
    model.profile = {"max_input_tokens": 1_000_000}
    agent = build_deep_agent(
        model=model,
        tools=[allowed_tool],
        system_prompt="system",
    )

    asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="hello")]}))
    names = {
        item["function"]["name"]
        for item in provider.bound_tools
        if item.get("type") == "function"
    }
    assert "allowed_tool" in names
    assert "read_file" in names
    assert names.isdisjoint(DEEP_AGENT_FORBIDDEN_TOOLS)


def _compact_eligible_history() -> list:
    """近似 token 低于自动压缩线，已上报用量达到主动压缩线。"""
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.messages.utils import count_tokens_approximately

    recent = HumanMessage(content="RECENT_MARKER")
    reported = AIMessage(
        content="先前回复",
        usage_metadata={"input_tokens": 3500, "output_tokens": 500, "total_tokens": 4000},
        response_metadata={"model_provider": "novel"},
    )
    size = 4000
    while True:
        old = HumanMessage(content=f"LONG_HISTORY_MARKER {'甲' * size} TAIL_MARKER")
        messages = [old, reported, recent]
        count = count_tokens_approximately(messages)
        if 1000 <= count < 3000:
            return messages
        if count >= 3000:
            raise AssertionError(f"历史近似 token 过高: {count}")
        size += 1000


class CompactingProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.seen: list[list] = []

    async def stream_chat(self, messages, *, client=None, tools=None, raw_event_hook=None, tool_choice=None):
        self.bound_tools = tools
        self.seen.append(messages)
        blob = str(messages)
        if "Context Extraction Assistant" in blob:
            assert "LONG_HISTORY_MARKER" in blob
            assert "TAIL_MARKER" in blob
            yield ToolStreamEvent(kind="text", text="SUMMARY_TOKEN")
            return
        if "LONG_HISTORY_MARKER" in blob:
            from services.llm.llm_tool import ToolCallFinished

            yield ToolStreamEvent(
                kind="usage",
                usage={"input_tokens": 3500, "output_tokens": 500, "total_tokens": 4000},
            )
            yield ToolStreamEvent(
                kind="tool_call",
                tool_call=ToolCallFinished(
                    tool_name="compact_conversation",
                    call_id="compact-1",
                    arguments={},
                ),
            )
            return
        assert "SUMMARY_TOKEN" in blob
        assert "RECENT_MARKER" in blob
        assert "LONG_HISTORY_MARKER" not in blob
        yield ToolStreamEvent(kind="text", text="压缩后继续")


class OverflowProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def stream_chat(self, messages, *, client=None, tools=None, raw_event_hook=None, tool_choice=None):
        from langchain_core.exceptions import ContextOverflowError

        self.calls += 1
        raise ContextOverflowError("context window exceeded")
        yield ToolStreamEvent(kind="text", text="")


def test_compact_conversation_is_visible_and_next_model_call_uses_summary():
    provider = CompactingProvider()
    model = DeepAgentChatModel(provider=provider, model_name="test-model")
    model.profile = {"max_input_tokens": 8000}
    agent = build_deep_agent(
        model=model,
        tools=[allowed_tool],
        system_prompt="system",
    )
    history = _compact_eligible_history()

    result = asyncio.run(agent.ainvoke({"messages": history}))

    names = {
        item["function"]["name"]
        for item in provider.bound_tools
        if item.get("type") == "function"
    }
    assert "compact_conversation" in names
    assert "read_file" in names
    assert names.isdisjoint(DEEP_AGENT_FORBIDDEN_TOOLS)
    assert result["messages"][-1].content == "压缩后继续"
    assert any("SUMMARY_TOKEN" in str(messages) for messages in provider.seen)


def test_context_overflow_is_not_rewritten_into_another_model_call():
    provider = OverflowProvider()
    model = DeepAgentChatModel(provider=provider, model_name="test-model")
    model.profile = {"max_input_tokens": 1_000_000}
    agent = build_deep_agent(
        model=model,
        tools=[allowed_tool],
        system_prompt="system",
    )

    try:
        asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="hello")]}))
    except Exception as exc:
        assert "context window exceeded" in str(exc)
    else:
        raise AssertionError("超窗请求应失败")
    assert provider.calls == 1


def test_supervisor_run_uses_deep_agent_stream_and_emits_events(monkeypatch):
    provider = SupervisorProvider()
    model = DeepAgentChatModel(provider=provider, model_name="test-model")
    model.profile = {"max_input_tokens": 1_000_000}
    monkeypatch.setattr(
        "services.agents.llm.get_deep_agent_model",
        lambda **kwargs: model,
    )
    emitted = []

    async def emit(event, payload):
        emitted.append((event, payload))

    result = asyncio.run(SupervisorAgent().run("你好", context={}, emit=emit))

    assert result == {"success": True, "message": "已完成"}
    assert provider.calls == 1
    assert not any(event == "supervisor_stream" for event, _ in emitted)


def test_supervisor_retries_hidden_when_model_returns_without_tool(monkeypatch):
    provider = MissingToolThenFinishProvider()
    model = DeepAgentChatModel(provider=provider, model_name="test-model")
    model.profile = {"max_input_tokens": 1_000_000}
    monkeypatch.setattr(
        "services.agents.llm.get_deep_agent_model",
        lambda **kwargs: model,
    )

    result = asyncio.run(SupervisorAgent().run("完成任务", context={}))

    assert result == {"success": True, "message": "任务已经完成"}
    assert provider.calls == 2
    assert "必须使用 respond_to_user 工具来结束任务" in provider.seen[1][-1]["content"]


def test_supervisor_does_not_emit_internal_summarization_stream(monkeypatch):
    from langchain_core.messages import AIMessage, AIMessageChunk

    class Graph:
        async def astream(self, state, **kwargs):
            yield "messages", (
                AIMessageChunk(content="## SESSION INTENT\n内部摘要"),
                {"langgraph_node": "model", "lc_source": "summarization"},
            )
            yield "updates", {"model": {"messages": [AIMessage(content="正式回复")]}}

    monkeypatch.setattr(SupervisorAgent, "_build_graph", lambda self, **kwargs: Graph())
    emitted = []

    async def emit(event, payload):
        emitted.append((event, payload))

    result = asyncio.run(SupervisorAgent().run("你好", context={}, emit=emit))

    streamed = "".join(
        payload.get("chunk", "") for event, payload in emitted
        if event == "supervisor_stream"
    )
    assert "SESSION INTENT" not in streamed
    assert result["message"] == "正式回复"
