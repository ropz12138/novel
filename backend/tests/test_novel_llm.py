"""NovelLLM：LangChain 消息面必须走 BaseLLMProvider。"""
import asyncio

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool as lc_tool

from services.llm.langchain_adapter import NovelLLM, langchain_messages_to_dicts
from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
from services.llm.llm_types import LLMModelConfig


@lc_tool
def _sample_tool(text: str) -> str:
    """示例工具"""
    return text


class _FakeProvider:
    def __init__(self, events):
        self.events = list(events)
        self.last = None
        self.config = LLMModelConfig(
            name="m",
            base_url="http://x",
            api_key="k",
            provider="openai",
            model="m",
            extra_body={"thinking": {"type": "adaptive"}},
        )
        self.fallback_config = None
        self.client = None
        self.fallback_client = None

    async def stream_chat(self, messages, *, client=None, tools=None, raw_event_hook=None, tool_choice=None):
        self.last = {
            "messages": list(messages),
            "tools": tools,
            "tool_choice": tool_choice,
        }
        for event in self.events:
            yield event


def test_langchain_messages_to_dicts_maps_roles_and_tool_calls():
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="hi"),
        AIMessage(
            content="",
            tool_calls=[{"name": "query_nodes", "args": {"a": 1}, "id": "c1"}],
            additional_kwargs={"reasoning_content": "想"},
        ),
        ToolMessage(content='{"ok":true}', tool_call_id="c1"),
    ]
    dicts = langchain_messages_to_dicts(messages)
    assert dicts[0] == {"role": "system", "content": "sys"}
    assert dicts[1] == {"role": "user", "content": "hi"}
    assert dicts[2]["role"] == "assistant"
    assert dicts[2]["reasoning_content"] == "想"
    assert dicts[2]["tool_calls"][0]["id"] == "c1"
    assert dicts[2]["tool_calls"][0]["function"]["name"] == "query_nodes"
    assert dicts[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok":true}'}


def test_novel_llm_astream_uses_provider_and_emits_chunks():
    provider = _FakeProvider(
        [
            ToolStreamEvent(kind="thinking", text="推理"),
            ToolStreamEvent(kind="text", text="正文"),
            ToolStreamEvent(
                kind="tool_call",
                tool_call=ToolCallFinished(
                    tool_name="query_nodes",
                    call_id="c1",
                    arguments={"limit": 1},
                ),
            ),
        ]
    )
    llm = NovelLLM(provider=provider, model_name="m", extra_body={"thinking": {"type": "adaptive"}})

    async def _run():
        chunks = []
        async for chunk in llm.astream([HumanMessage(content="hi")]):
            chunks.append(chunk)
        return chunks

    chunks = asyncio.run(_run())
    assert provider.last["messages"][0]["role"] == "user"
    assert [
        c.additional_kwargs.get("reasoning_content")
        for c in chunks
        if c.additional_kwargs.get("reasoning_content")
    ] == ["推理"]
    assert any(getattr(c, "content", "") == "正文" for c in chunks)
    aggregated = chunks[0]
    for c in chunks[1:]:
        aggregated = aggregated + c
    assert aggregated.tool_calls[0]["name"] == "query_nodes"


def test_bind_tools_uses_instance_extra_body():
    provider = _FakeProvider([])
    llm = NovelLLM(provider=provider, model_name="x", extra_body={"thinking": {"type": "adaptive"}})
    bound = llm.bind_tools([_sample_tool])
    assert bound.kwargs.get("extra_body") == {"thinking": {"type": "adaptive"}}
    assert bound._tools[0]["function"]["name"] == "_sample_tool"


def test_bind_tools_injects_nothing_when_extra_body_unset():
    provider = _FakeProvider([])
    llm = NovelLLM(provider=provider, model_name="x", extra_body=None)
    bound = llm.bind_tools([_sample_tool])
    eb = bound.kwargs.get("extra_body")
    assert not (eb and eb.get("thinking"))


def test_bind_tools_caller_extra_body_wins():
    provider = _FakeProvider([])
    llm = NovelLLM(provider=provider, model_name="x", extra_body={"thinking": {"type": "adaptive"}})
    bound = llm.bind_tools([_sample_tool], extra_body={"thinking": {"type": "disabled"}})
    assert bound.kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}


def test_bind_tools_named_tool_choice_passed_to_provider():
    provider = _FakeProvider([ToolStreamEvent(kind="text", text="x")])
    llm = NovelLLM(provider=provider, model_name="x")
    bound = llm.bind_tools([_sample_tool], tool_choice="_sample_tool")

    async def _run():
        async for _ in bound.astream([HumanMessage(content="hi")]):
            pass

    asyncio.run(_run())
    assert provider.last["tool_choice"] == "_sample_tool"
    assert provider.last["tools"][0]["function"]["name"] == "_sample_tool"
