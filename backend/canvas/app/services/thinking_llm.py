"""Thinking Mode ChatOpenAI 适配：reasoning_content 收发（DeepSeek / MiMo 等兼容 API）。

LangChain 标准 ChatOpenAI 不会：
1. 从 API 响应提取 reasoning_content 到 AIMessage.additional_kwargs
2. 在请求时将 additional_kwargs.reasoning_content 写回 API 载荷
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Literal

import openai
from pydantic import PrivateAttr
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import (
    _convert_delta_to_message_chunk,
    _convert_dict_to_message,
    _convert_from_v1_to_chat_completions,
    _convert_message_to_dict,
    _create_usage_metadata,
)

logger = logging.getLogger(__name__)


def _inject_reasoning_content_outbound(message_dict: dict[str, Any], message: BaseMessage) -> None:
    if not isinstance(message, AIMessage):
        return
    rc = message.additional_kwargs.get("reasoning_content")
    if rc is not None:
        message_dict["reasoning_content"] = rc


def thinking_convert_message_to_dict(
    message: BaseMessage,
    api: Literal["chat/completions", "responses"] = "chat/completions",
) -> dict[str, Any]:
    message_dict = _convert_message_to_dict(message, api=api)
    _inject_reasoning_content_outbound(message_dict, message)
    return message_dict


def thinking_convert_dict_to_message(_dict: Mapping[str, Any]) -> BaseMessage:
    message = _convert_dict_to_message(_dict)
    if isinstance(message, AIMessage):
        rc = _dict.get("reasoning_content")
        if rc is not None:
            message.additional_kwargs["reasoning_content"] = rc
    return message


def thinking_convert_delta_to_message_chunk(
    _dict: Mapping[str, Any],
    default_class: type,
) -> BaseMessage:
    chunk = _convert_delta_to_message_chunk(_dict, default_class)
    if isinstance(chunk, AIMessageChunk):
        rc = _dict.get("reasoning_content")
        if rc is not None:
            chunk.additional_kwargs["reasoning_content"] = rc
    return chunk


def repair_tool_call_arguments(raw: str) -> str:
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    fixed = _escape_unescaped_quotes_in_json(raw)
    try:
        json.loads(fixed)
        return fixed
    except json.JSONDecodeError as e:
        raise ValueError(f"tool-call arguments JSON 修复失败: {e}") from e


def _escape_unescaped_quotes_in_json(raw: str) -> str:
    result: list[str] = []
    i = 0
    in_string = False
    n = len(raw)

    while i < n:
        ch = raw[i]

        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue

        if ch == '\\':
            result.append(ch)
            if i + 1 < n:
                i += 1
                result.append(raw[i])
            i += 1
            continue

        if ch == '"':
            j = i + 1
            while j < n and raw[j] in (' ', '\t', '\n', '\r'):
                j += 1
            next_ch = raw[j] if j < n else ''

            if next_ch in (',', '}', ']', ':', '') or (next_ch == ')' and j == n - 1):
                result.append('"')
                in_string = False
            else:
                result.append('\\"')
            i += 1
            continue

        result.append(ch)
        i += 1

    return ''.join(result)


class FallbackLLM(Runnable):
    """包装 ThinkingChatOpenAI，主模型任意业务报错都自动切换到备选模型重试。

    系统级异常（KeyboardInterrupt / GeneratorExit / asyncio.CancelledError 等
    ``BaseException``）不会被 ``except Exception`` 捕获，自然向上传播、不触发切换。
    流式方法在主模型已吐出部分内容后报错，也会从头重流备用模型（可能产生前缀重复，
    由调用方决定如何处理）。
    """

    def __init__(self, primary: ThinkingChatOpenAI, fallback: ThinkingChatOpenAI):
        self._primary = primary
        self._fallback = fallback

    def __getattr__(self, name: str):
        return getattr(self._primary, name)

    def bind_tools(self, tools, **kwargs):
        return FallbackLLM(
            self._primary.bind_tools(tools, **kwargs),
            self._fallback.bind_tools(tools, **kwargs),
        )

    def with_structured_output(self, schema, **kwargs):
        return FallbackLLM(
            self._primary.with_structured_output(schema, **kwargs),
            self._fallback.with_structured_output(schema, **kwargs),
        )

    def invoke(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            return self._primary.invoke(input, config=config, **kwargs)
        except Exception as e:
            logger.warning(
                "主模型 %s 调用失败 (%s: %s)，切换到备用模型 %s",
                self._primary.model_name, type(e).__name__, e, self._fallback.model_name,
            )
            return self._fallback.invoke(input, config=config, **kwargs)

    async def ainvoke(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            return await self._primary.ainvoke(input, config=config, **kwargs)
        except Exception as e:
            logger.warning(
                "主模型 %s 调用失败 (%s: %s)，切换到备用模型 %s",
                self._primary.model_name, type(e).__name__, e, self._fallback.model_name,
            )
            return await self._fallback.ainvoke(input, config=config, **kwargs)

    def stream(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            yield from self._primary.stream(input, config=config, **kwargs)
        except Exception as e:
            logger.warning(
                "主模型 %s 流式调用失败 (%s: %s)，切换到备用模型 %s 从头重流",
                self._primary.model_name, type(e).__name__, e, self._fallback.model_name,
            )
            yield from self._fallback.stream(input, config=config, **kwargs)

    async def astream(self, input, config: RunnableConfig | None = None, **kwargs):
        try:
            async for chunk in self._primary.astream(input, config=config, **kwargs):
                yield chunk
        except Exception as e:
            logger.warning(
                "主模型 %s 流式调用失败 (%s: %s)，切换到备用模型 %s 从头重流",
                self._primary.model_name, type(e).__name__, e, self._fallback.model_name,
            )
            async for chunk in self._fallback.astream(input, config=config, **kwargs):
                yield chunk


class ThinkingChatOpenAI(ChatOpenAI):
    """兼容 Thinking Mode 的 ChatOpenAI 子类（DeepSeek / MiMo 等）。

    thinking 等额外 API 参数从 config 读入实例 ``_extra_body``，在 bind_tools /
    with_structured_output 时透传；未配置则不注入任何 extra 参数，由模型用自身默认。
    调用方显式传入的 ``extra_body`` 优先于实例配置。
    """

    _extra_body: dict | None = PrivateAttr(default=None)

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        if "extra_body" not in kwargs and self._extra_body:
            kwargs["extra_body"] = self._extra_body
        return super().bind_tools(tools, **kwargs)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        if "extra_body" not in kwargs and self._extra_body:
            kwargs["extra_body"] = self._extra_body
        return super().with_structured_output(schema, **kwargs)

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if "messages" not in payload:
            return payload
        messages = self._convert_input(input_).to_messages()
        payload["messages"] = [
            thinking_convert_message_to_dict(
                _convert_from_v1_to_chat_completions(m) if isinstance(m, AIMessage) else m
            )
            if isinstance(m, AIMessage)
            else thinking_convert_message_to_dict(m)
            for m in messages
        ]
        return payload

    def _create_chat_result(
        self,
        response: dict | openai.BaseModel,
        generation_info: dict | None = None,
    ) -> ChatResult:
        from langchain_core.outputs import ChatGeneration

        generations = []

        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        if response_dict.get("error"):
            raise ValueError(response_dict.get("error"))

        choices = response_dict["choices"]
        if choices is None:
            raise TypeError(
                "Received response with null value for 'choices'. "
                f"Full response keys: {list(response_dict.keys())}"
            )

        token_usage = response_dict.get("usage")
        service_tier = response_dict.get("service_tier")

        for res in choices:
            raw_msg = res["message"]
            raw_tool_calls = raw_msg.get("tool_calls")
            if raw_tool_calls and isinstance(raw_tool_calls, list):
                for tc in raw_tool_calls:
                    func = tc.get("function")
                    if func and isinstance(func, dict) and "arguments" in func:
                        args_str = func["arguments"]
                        if isinstance(args_str, str):
                            try:
                                json.loads(args_str)
                            except json.JSONDecodeError:
                                try:
                                    func["arguments"] = repair_tool_call_arguments(args_str)
                                except ValueError:
                                    pass

            message = thinking_convert_dict_to_message(raw_msg)
            if token_usage and isinstance(message, AIMessage):
                message.usage_metadata = _create_usage_metadata(token_usage, service_tier)
            gen_info = generation_info or {}
            gen_info["finish_reason"] = (
                res.get("finish_reason")
                if res.get("finish_reason") is not None
                else gen_info.get("finish_reason")
            )
            if "logprobs" in res:
                gen_info["logprobs"] = res["logprobs"]
            generations.append(ChatGeneration(message=message, generation_info=gen_info))

        llm_output = {
            "token_usage": token_usage,
            "model_provider": "openai",
            "model_name": response_dict.get("model", self.model_name),
            "system_fingerprint": response_dict.get("system_fingerprint", ""),
        }
        if "id" in response_dict:
            llm_output["id"] = response_dict["id"]
        if service_tier:
            llm_output["service_tier"] = service_tier

        if isinstance(response, openai.BaseModel) and getattr(response, "choices", None):
            oai_message = response.choices[0].message
            if hasattr(oai_message, "parsed"):
                generations[0].message.additional_kwargs["parsed"] = oai_message.parsed
            if hasattr(oai_message, "refusal"):
                generations[0].message.additional_kwargs["refusal"] = oai_message.refusal
            rc = getattr(oai_message, "reasoning_content", None)
            if rc is not None and isinstance(generations[0].message, AIMessage):
                generations[0].message.additional_kwargs["reasoning_content"] = rc

        return ChatResult(generations=generations, llm_output=llm_output)

    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict,
        default_chunk_class: type,
        base_generation_info: dict | None,
    ) -> ChatGenerationChunk | None:
        if chunk.get("type") == "content.delta":
            return None
        token_usage = chunk.get("usage")
        choices = chunk.get("choices", []) or chunk.get("chunk", {}).get("choices", [])

        usage_metadata = (
            _create_usage_metadata(token_usage, chunk.get("service_tier"))
            if token_usage
            else None
        )
        if len(choices) == 0:
            generation_chunk = ChatGenerationChunk(
                message=default_chunk_class(content="", usage_metadata=usage_metadata),
                generation_info=base_generation_info,
            )
            if self.output_version == "v1":
                generation_chunk.message.content = []
                generation_chunk.message.response_metadata["output_version"] = "v1"
            return generation_chunk

        choice = choices[0]
        if choice["delta"] is None:
            return None

        message_chunk = thinking_convert_delta_to_message_chunk(
            choice["delta"],
            default_chunk_class,
        )
        generation_info = {**base_generation_info} if base_generation_info else {}

        if finish_reason := choice.get("finish_reason"):
            generation_info["finish_reason"] = finish_reason
            if model_name := chunk.get("model"):
                generation_info["model_name"] = model_name
            if system_fingerprint := chunk.get("system_fingerprint"):
                generation_info["system_fingerprint"] = system_fingerprint
            if service_tier := chunk.get("service_tier"):
                generation_info["service_tier"] = service_tier

        logprobs = choice.get("logprobs")
        if logprobs:
            generation_info["logprobs"] = logprobs

        if usage_metadata and isinstance(message_chunk, AIMessageChunk):
            message_chunk.usage_metadata = usage_metadata

        message_chunk.response_metadata["model_provider"] = "openai"
        return ChatGenerationChunk(
            message=message_chunk,
            generation_info=generation_info or None,
        )
