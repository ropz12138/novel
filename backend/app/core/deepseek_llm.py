"""DeepSeek ChatOpenAI 适配：Thinking Mode 下 reasoning_content 的收发。

LangChain 标准 ChatOpenAI 不会：
1. 从 API 响应提取 reasoning_content 到 AIMessage.additional_kwargs
2. 在请求时将 additional_kwargs.reasoning_content 写回 API 载荷

DeepSeek Thinking Mode + Tool Calls 要求带 tool_calls 的 assistant 消息必须传回 reasoning_content。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Literal

import openai
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from langchain_openai.chat_models.base import (
    _convert_delta_to_message_chunk,
    _convert_dict_to_message,
    _convert_from_v1_to_chat_completions,
    _convert_message_to_dict,
    _create_usage_metadata,
)


def _inject_reasoning_content_outbound(message_dict: dict[str, Any], message: BaseMessage) -> None:
    """将 AIMessage.additional_kwargs['reasoning_content'] 写入请求 dict 顶层字段。"""
    if not isinstance(message, AIMessage):
        return
    rc = message.additional_kwargs.get("reasoning_content")
    if rc is not None:
        message_dict["reasoning_content"] = rc


def deepseek_convert_message_to_dict(
    message: BaseMessage,
    api: Literal["chat/completions", "responses"] = "chat/completions",
) -> dict[str, Any]:
    message_dict = _convert_message_to_dict(message, api=api)
    _inject_reasoning_content_outbound(message_dict, message)
    return message_dict


def deepseek_convert_dict_to_message(_dict: Mapping[str, Any]) -> BaseMessage:
    message = _convert_dict_to_message(_dict)
    if isinstance(message, AIMessage):
        rc = _dict.get("reasoning_content")
        if rc is not None:
            message.additional_kwargs["reasoning_content"] = rc
    return message


def deepseek_convert_delta_to_message_chunk(
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
    """尝试修复 LLM tool-call arguments 中未转义的双引号。

    DeepSeek 等 LLM 有时在 JSON 字符串值内输出未转义的英文双引号，
    导致 JSON 解析失败。此函数通过将字符串值内部的裸双引号替换为
    转义双引号来修复。

    修复失败时抛出 ValueError。
    """
    # 先试原样解析
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        pass

    # 尝试逐字符扫描修复：找到字符串值内的裸双引号并转义
    fixed = _escape_unescaped_quotes_in_json(raw)

    # 验证修复后的 JSON
    try:
        json.loads(fixed)
        return fixed
    except json.JSONDecodeError as e:
        raise ValueError(f"tool-call arguments JSON 修复失败: {e}") from e


def _escape_unescaped_quotes_in_json(raw: str) -> str:
    """扫描 JSON 字符串，转义字符串值内部出现的裸双引号。

    策略：逐字符遍历，跟踪当前是否在字符串内部（被双引号包围）。
    在字符串内部遇到的双引号，如果后面跟着逗号、右花/方括号、冒号、
    或字符串末尾，说明它是 JSON 结构引号，保留；否则转义。
    """
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

        # 在字符串内部
        if ch == '\\':
            # 已转义的字符，直接保留接下来两个字符
            result.append(ch)
            if i + 1 < n:
                i += 1
                result.append(raw[i])
            i += 1
            continue

        if ch == '"':
            # 判断这是否是 JSON 结构的结束引号
            # 向后看：跳过空白后，下一个字符应该是 , } ] : 或字符串末尾
            j = i + 1
            while j < n and raw[j] in (' ', '\t', '\n', '\r'):
                j += 1
            next_ch = raw[j] if j < n else ''

            if next_ch in (',', '}', ']', ':', '') or (next_ch == ')' and j == n - 1):
                # 这是结构性的结束引号
                result.append('"')
                in_string = False
            else:
                # 字符串值内部的裸双引号，需要转义
                result.append('\\"')
            i += 1
            continue

        result.append(ch)
        i += 1

    return ''.join(result)


class DeepSeekChatOpenAI(ChatOpenAI):
    """兼容 DeepSeek Thinking Mode 的 ChatOpenAI 子类。

    bind_tools 自动注入 extra_body={"thinking": {"type": "disabled"}} 关闭思考模式，
    使 tool-calling 快速返回，无需等待推理过程。
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        """bind_tools 时自动关闭思考模式以加速 tool-calling。"""
        existing_extra = kwargs.get("extra_body") or {}
        if "thinking" not in existing_extra:
            kwargs["extra_body"] = {**existing_extra, "thinking": {"type": "disabled"}}
        return super().bind_tools(tools, **kwargs)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """with_structured_output 时自动关闭思考模式。"""
        existing_extra = kwargs.get("extra_body") or {}
        if "thinking" not in existing_extra:
            kwargs["extra_body"] = {**existing_extra, "thinking": {"type": "disabled"}}
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
            deepseek_convert_message_to_dict(
                _convert_from_v1_to_chat_completions(m) if isinstance(m, AIMessage) else m
            )
            if isinstance(m, AIMessage)
            else deepseek_convert_message_to_dict(m)
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

        try:
            choices = response_dict["choices"]
        except KeyError as e:
            msg = f"Response missing 'choices' key: {response_dict.keys()}"
            raise KeyError(msg) from e

        if choices is None:
            msg = (
                "Received response with null value for 'choices'. "
                f"Full response keys: {list(response_dict.keys())}"
            )
            raise TypeError(msg)

        token_usage = response_dict.get("usage")
        service_tier = response_dict.get("service_tier")

        for res in choices:
            # 预修复 tool_call arguments 中未转义的双引号
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
                                    pass  # 修复失败，保留原始值，后续会报错

            message = deepseek_convert_dict_to_message(raw_msg)
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

        message_chunk = deepseek_convert_delta_to_message_chunk(
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
