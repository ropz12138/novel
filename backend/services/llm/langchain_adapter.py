"""把 BaseLLMProvider 接到现有 LangChain / LangGraph 调用面。"""
from __future__ import annotations

import json
import uuid
from typing import Any, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict, Field
from langchain_core.utils.function_calling import convert_to_openai_tool

from services.agents.embedded_tool_content import EMBEDDED_TOOL_MODEL, parse_embedded_tool_content
from services.llm.llm_service import BaseLLMProvider, create_provider
from services.llm.llm_tool import ToolCallFinished, ToolStreamEvent
from services.llm.llm_types import LLMModelConfig
from services.llm_stream import chunk_to_ai_message


async def normalize_provider_events(events, *, model_name: str):
    """仅 deepseek-v4-flash-0731 在没有 reasoning_content 时，拆开塞进正文的思考和工具调用。"""
    if model_name != EMBEDDED_TOOL_MODEL:
        async for event in events:
            yield event
        return
    buffered: list[str] = []
    saw_tool = False
    saw_reasoning = False
    async for event in events:
        if event.kind == "thinking" and event.text:
            saw_reasoning = True
            yield event
            continue
        if event.kind == "text":
            buffered.append(event.text)
            continue
        if event.kind == "tool_call":
            saw_tool = True
            if buffered:
                yield ToolStreamEvent(kind="text", text="".join(buffered))
                buffered.clear()
            yield event
            continue
        yield event
    text = "".join(buffered)
    if saw_tool or saw_reasoning:
        if text:
            yield ToolStreamEvent(kind="text", text=text)
        return
    parsed = parse_embedded_tool_content(text)
    if parsed is None:
        if text:
            yield ToolStreamEvent(kind="text", text=text)
        return
    if parsed.reasoning:
        yield ToolStreamEvent(kind="thinking", text=parsed.reasoning)
    if parsed.content:
        yield ToolStreamEvent(kind="text", text=parsed.content)
    for call in parsed.tool_calls:
        yield ToolStreamEvent(
            kind="tool_call",
            tool_call=ToolCallFinished(
                tool_name=call["name"],
                call_id=f"call_embedded_{uuid.uuid4().hex[:12]}",
                arguments=call["arguments"],
            ),
        )


_ROLE_MAP = {
    "human": "user",
    "ai": "assistant",
    "system": "system",
    "tool": "tool",
    "user": "user",
    "assistant": "assistant",
}


def langchain_messages_to_dicts(messages: Sequence[Any] | str) -> list[dict[str, Any]]:
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]
    out: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, dict):
            out.append(dict(message))
            continue
        if isinstance(message, ToolMessage):
            out.append({
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content,
            })
            continue
        if isinstance(message, AIMessage):
            payload: dict[str, Any] = {
                "role": "assistant",
                "content": message.content or "",
            }
            tool_calls = getattr(message, "tool_calls", None) or []
            if tool_calls:
                payload["tool_calls"] = []
                for call in tool_calls:
                    args = call.get("args") if isinstance(call, dict) else {}
                    payload["tool_calls"].append({
                        "id": call.get("id") if isinstance(call, dict) else "",
                        "type": "function",
                        "function": {
                            "name": call.get("name") if isinstance(call, dict) else "",
                            "arguments": json.dumps(args or {}, ensure_ascii=False),
                        },
                    })
            reasoning = (getattr(message, "additional_kwargs", None) or {}).get("reasoning_content")
            if reasoning:
                payload["reasoning_content"] = reasoning
            out.append(payload)
            continue
        if isinstance(message, BaseMessage):
            role = _ROLE_MAP.get(getattr(message, "type", ""), None)
            if role is None:
                raise ValueError(f"不支持的 message type: {getattr(message, 'type', None)}")
            out.append({"role": role, "content": message.content})
            continue
        raise TypeError(f"不支持的消息类型: {type(message)}")
    return out


def _convert_tools(tools: list[Any] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    converted = []
    for tool in tools:
        if isinstance(tool, dict) and tool.get("type") == "function":
            converted.append(tool)
        else:
            converted.append(convert_to_openai_tool(tool))
    return converted


class NovelLLM:
    """项目 LLM 入口：HTTP 只经 BaseLLMProvider，对外保持 astream/ainvoke/bind_tools。"""

    def __init__(
        self,
        *,
        provider: BaseLLMProvider,
        model_name: str,
        extra_body: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
    ) -> None:
        self.provider = provider
        self.model_name = model_name
        self._extra_body = extra_body
        self._tools = tools
        self._tool_choice = tool_choice
        self.kwargs = {"extra_body": extra_body} if extra_body else {}
        self._primary = self
        self._fallback = None
        if provider.fallback_config is not None:
            inner = type("FallbackIdentity", (), {})()
            inner.model_name = provider.fallback_config.name
            inner._extra_body = dict(provider.fallback_config.extra_body)
            self._fallback = inner

    @classmethod
    def from_configs(
        cls,
        primary: LLMModelConfig,
        fallback: LLMModelConfig | None = None,
    ) -> "NovelLLM":
        extra = {
            key: value
            for key, value in dict(primary.extra_body or {}).items()
            if key != "temperature"
        }
        return cls(
            provider=create_provider(primary, fallback),
            model_name=primary.name,
            extra_body=extra or None,
        )

    def bind_tools(self, tools, tool_choice=None, extra_body=None, **kwargs):
        resolved_extra = extra_body if extra_body is not None else self._extra_body
        bound = NovelLLM(
            provider=self.provider,
            model_name=self.model_name,
            extra_body=resolved_extra,
            tools=_convert_tools(list(tools)),
            tool_choice=tool_choice,
        )
        bound._fallback = self._fallback
        return bound

    def invoke(self, input, config=None, **kwargs):
        text = self.provider.complete(langchain_messages_to_dicts(input))
        return AIMessage(content=text)

    async def ainvoke(self, input, config=None, **kwargs):
        aggregated = None
        async for chunk in self.astream(input, config=config, **kwargs):
            aggregated = chunk if aggregated is None else aggregated + chunk
        if aggregated is None:
            raise RuntimeError("LLM 未返回任何响应")
        return chunk_to_ai_message(aggregated)

    def stream(self, input, config=None, **kwargs):
        raise NotImplementedError("NovelLLM 只提供 astream")

    async def astream(self, input, config=None, **kwargs):
        messages = langchain_messages_to_dicts(input)
        tool_index = 0
        async for event in normalize_provider_events(self.provider.stream_chat(
            messages,
            tools=self._tools,
            tool_choice=self._tool_choice,
        ), model_name=self.model_name):
            if event.kind == "thinking":
                yield AIMessageChunk(
                    content="",
                    additional_kwargs={"reasoning_content": event.text},
                )
            elif event.kind == "text":
                yield AIMessageChunk(content=event.text)
            elif event.kind == "tool_call" and event.tool_call is not None:
                call = event.tool_call
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=[{
                        "name": call.tool_name,
                        "args": json.dumps(call.arguments, ensure_ascii=False),
                        "id": call.call_id,
                        "index": tool_index,
                        "type": "tool_call_chunk",
                    }],
                    response_metadata={"finish_reason": "tool_calls"},
                )
                tool_index += 1
            elif event.kind == "usage" and event.usage is not None:
                yield AIMessageChunk(content="", usage_metadata=event.usage)


class DeepAgentChatModel(BaseChatModel):
    """让 Deep Agents 通过项目 BaseLLMProvider 调用模型。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: Any = Field(exclude=True)
    model_name: str
    extra_body: dict[str, Any] | None = None
    bound_tools: list[dict[str, Any]] | None = Field(default=None, exclude=True)
    tool_choice: Any = Field(default=None, exclude=True)

    @property
    def _llm_type(self) -> str:
        return "novel"

    def _get_ls_params(self, stop=None, **kwargs):
        return {
            "ls_provider": "novel",
            "ls_model_name": self.model_name,
            "ls_model_type": "chat",
        }

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self.model_copy(update={
            "bound_tools": _convert_tools(list(tools)),
            "tool_choice": tool_choice,
        })

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        text = self.provider.complete(langchain_messages_to_dicts(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        aggregated = None
        async for generation_chunk in self._astream(
            messages,
            stop=stop,
            run_manager=run_manager,
            **kwargs,
        ):
            aggregated = generation_chunk if aggregated is None else aggregated + generation_chunk
        if aggregated is None:
            raise RuntimeError("LLM 未返回任何响应")
        return ChatResult(generations=[ChatGeneration(message=chunk_to_ai_message(aggregated.message))])

    def _chunk(self, **kwargs) -> AIMessageChunk:
        metadata = dict(kwargs.pop("response_metadata", None) or {})
        metadata["model_provider"] = self._get_ls_params().get("ls_provider")
        return AIMessageChunk(response_metadata=metadata, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        tool_index = 0
        async for event in normalize_provider_events(self.provider.stream_chat(
            langchain_messages_to_dicts(messages),
            tools=self.bound_tools,
            tool_choice=self.tool_choice,
        ), model_name=self.model_name):
            if event.kind == "thinking":
                message = self._chunk(
                    content="",
                    additional_kwargs={"reasoning_content": event.text},
                )
            elif event.kind == "text":
                message = self._chunk(content=event.text)
            elif event.kind == "tool_call" and event.tool_call is not None:
                call = event.tool_call
                message = self._chunk(
                    content="",
                    tool_call_chunks=[{
                        "name": call.tool_name,
                        "args": json.dumps(call.arguments, ensure_ascii=False),
                        "id": call.call_id,
                        "index": tool_index,
                        "type": "tool_call_chunk",
                    }],
                    response_metadata={"finish_reason": "tool_calls"},
                )
                tool_index += 1
            elif event.kind == "usage" and event.usage is not None:
                message = self._chunk(content="", usage_metadata=event.usage)
            else:
                continue
            yield ChatGenerationChunk(message=message)
