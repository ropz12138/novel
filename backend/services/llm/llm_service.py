"""自研 LLM 层：httpx 直连 OpenAI / Anthropic，无 LangChain 传输依赖。

业务入口是 BaseLLMProvider / NovelLLM；不要直接实例化协议客户端。
"""
from __future__ import annotations

import copy
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any

import httpx

from services.llm.llm_complete_utils import (
    LLMCompleteError,
    extract_anthropic_text,
    extract_openai_text,
)
from services.llm.llm_raw_log import LLMRawLog
from services.llm.llm_tool import (
    ToolCallFinished,
    ToolStreamEvent,
)
from services.llm.llm_types import LLMModelConfig

logger = logging.getLogger("llm")

LLMRawEventHook = Callable[[dict[str, Any]], None]


def resolve_openai_tool_choice(tool_choice):
    if tool_choice is None:
        return "auto"
    if isinstance(tool_choice, str) and tool_choice not in ("auto", "none", "required"):
        return {"type": "function", "function": {"name": tool_choice}}
    return tool_choice


def response_format_json_retryable(detail: str) -> bool:
    text = detail.lower()
    return "response_format" in text or "json_object" in text


async def _raise_for_status_with_body(response: httpx.Response, config: LLMModelConfig) -> None:
    if response.is_success:
        return
    body = (await response.aread()).decode("utf-8", errors="replace")
    message = (
        f"LLM 请求失败: provider={config.provider} model={config.model} "
        f"url={response.request.url} status={response.status_code} body={body}"
    )
    logger.error(message)
    raise httpx.HTTPStatusError(message, request=response.request, response=response)


class LLMProtocolClient(ABC):
    def __init__(self, config: LLMModelConfig) -> None:
        self.config = config

    @abstractmethod
    async def stream_chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        client: httpx.AsyncClient | None = None,
        tools: list[dict[str, Any]] | None = None,
        raw_event_hook: LLMRawEventHook | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> AsyncIterator[ToolStreamEvent]:
        raise NotImplementedError

    @abstractmethod
    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        temperature: float = 0.2,
        timeout_seconds: int = 120,
        response_format_json: bool = False,
        client: httpx.Client | None = None,
    ) -> str:
        raise NotImplementedError

    @staticmethod
    def _normalize_messages(messages: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [dict(message) for message in messages]

    @staticmethod
    def _join_url(base_url: str, path: str) -> str:
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _finalize_openai_pending(pending: dict[int, dict[str, Any]]) -> list[ToolStreamEvent]:
    events: list[ToolStreamEvent] = []
    for idx in sorted(list(pending.keys())):
        slot = pending.pop(idx)
        arguments_raw = "".join(slot["arguments_parts"])
        try:
            arguments = json.loads(arguments_raw) if arguments_raw else {}
        except json.JSONDecodeError:
            arguments = {"_raw_arguments": arguments_raw}
        events.append(
            ToolStreamEvent(
                kind="tool_call",
                tool_call=ToolCallFinished(
                    tool_name=slot["name"] or "",
                    call_id=slot["id"] or "",
                    arguments=arguments if isinstance(arguments, dict) else {"value": arguments},
                ),
            )
        )
    return events


class OpenAILLMClient(LLMProtocolClient):
    def _openai_complete_payload(self, messages, *, temperature: float, response_format_json: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._normalize_messages(messages),
            "temperature": temperature,
            "stream": False,
        }
        payload.update(copy.deepcopy(self.config.extra_body))
        if response_format_json:
            payload["response_format"] = {"type": "json_object"}
        if self.config.enable_thinking is not None:
            payload["enable_thinking"] = self.config.enable_thinking
        return payload

    def _openai_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _handle_complete_response(self, response: httpx.Response, payload: dict[str, Any], raw_log: LLMRawLog, retry_post):
        raw_log.raw_response(response.content, status_code=response.status_code)
        if response.status_code >= 400:
            detail = response.text[:500]
            if response_format_json_retryable(detail) and "response_format" in payload:
                payload = dict(payload)
                payload.pop("response_format", None)
                raw_log.finish()
                return retry_post(payload)
            raise LLMCompleteError(f"模型接口返回 HTTP {response.status_code}：{response.text[:500]}")
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMCompleteError(f"模型接口返回非 JSON：{response.text[:500] or '(空响应体)'}") from exc
        raw_log.finish()
        if not isinstance(body, dict):
            raise LLMCompleteError("模型接口返回不是 JSON 对象")
        return body

    def complete(self, messages, *, temperature=0.2, timeout_seconds=120, response_format_json=False, client=None) -> str:
        payload = self._openai_complete_payload(messages, temperature=temperature, response_format_json=response_format_json)
        url = self._join_url(self.config.base_url, "/chat/completions")
        owns = client is None
        active = client or httpx.Client(timeout=timeout_seconds)
        raw_log = LLMRawLog(provider=self.config.provider, model=self.config.model, mode="complete")
        raw_log.request(url=url, payload=payload)
        try:
            def retry_post(next_payload):
                retry_log = LLMRawLog(provider=self.config.provider, model=self.config.model, mode="complete_retry")
                retry_log.request(url=url, payload=next_payload)
                resp = active.post(url, headers=self._openai_headers(), json=next_payload)
                return self._handle_complete_response(resp, next_payload, retry_log, retry_post)

            response = active.post(url, headers=self._openai_headers(), json=payload)
            body = self._handle_complete_response(response, payload, raw_log, retry_post)
        except Exception as exc:
            raw_log.fail(exc)
            if not isinstance(exc, httpx.HTTPError):
                raise
            raise LLMCompleteError(f"模型接口连接失败：{exc}") from exc
        finally:
            if owns:
                active.close()
        return extract_openai_text(body)

    async def stream_chat(
        self,
        messages,
        *,
        client=None,
        tools=None,
        raw_event_hook=None,
        tool_choice=None,
    ) -> AsyncIterator[ToolStreamEvent]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": self._normalize_messages(messages),
            "stream": True,
        }
        payload.update(copy.deepcopy(self.config.extra_body))
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = resolve_openai_tool_choice(tool_choice)
        if self.config.enable_thinking is not None:
            payload["enable_thinking"] = self.config.enable_thinking
        headers = self._openai_headers()
        url = self._join_url(self.config.base_url, "/chat/completions")
        owns_client = client is None
        active_client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
        pending: dict[int, dict[str, Any]] = {}
        raw_log = LLMRawLog(provider=self.config.provider, model=self.config.model, mode="stream")
        raw_log.request(url=url, payload=payload)
        try:
            async with active_client.stream("POST", url, headers=headers, json=payload) as response:
                await _raise_for_status_with_body(response, self.config)
                async for line in response.aiter_lines():
                    raw_log.stream_line(line) if hasattr(raw_log, "stream_line") else None
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        for event in _finalize_openai_pending(pending):
                            yield event
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"SSE 行解析失败：{data[:200]}") from exc
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta", {})
                    finish_reason = choice.get("finish_reason") or delta.get("finish_reason")
                    text = delta.get("content")
                    if text:
                        yield ToolStreamEvent(kind="text", text=text)
                    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                    if reasoning:
                        yield ToolStreamEvent(kind="thinking", text=reasoning)
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = pending.setdefault(idx, {"id": None, "name": None, "arguments_parts": []})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["arguments_parts"].append(fn["arguments"])
                    if finish_reason == "tool_calls":
                        for event in _finalize_openai_pending(pending):
                            yield event
            raw_log.finish()
        except Exception as exc:
            raw_log.fail(exc)
            raise
        finally:
            if owns_client:
                await active_client.aclose()


class AnthropicLLMClient(LLMProtocolClient):
    @staticmethod
    def convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        for tool in tools:
            fn = tool.get("function", tool)
            converted.append({
                "name": fn["name"],
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            })
        return converted

    @staticmethod
    def _parse_tool_arguments(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if raw is None:
            return {}
        if not isinstance(raw, str):
            return {"value": raw}
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"_raw_arguments": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}

    @classmethod
    def convert_messages(cls, messages: Sequence[Mapping[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        anthropic_messages: list[dict[str, Any]] = []
        pending_tool_results: list[dict[str, Any]] = []

        def flush_tool_results() -> None:
            nonlocal pending_tool_results
            if not pending_tool_results:
                return
            anthropic_messages.append({"role": "user", "content": pending_tool_results})
            pending_tool_results = []

        for message in messages:
            role = str(message.get("role") or "")
            if role == "system":
                content = message.get("content")
                if content is None:
                    continue
                system_parts.append(content if isinstance(content, str) else json.dumps(content, ensure_ascii=False))
                continue
            if role == "tool":
                tool_call_id = str(message.get("tool_call_id") or "")
                if not tool_call_id:
                    raise ValueError("Anthropic 适配要求 tool 消息必须包含 tool_call_id")
                raw_content = message.get("content")
                tool_content = raw_content if isinstance(raw_content, str) else json.dumps(raw_content or "", ensure_ascii=False)
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": tool_content if isinstance(tool_content, str) else json.dumps(tool_content, ensure_ascii=False),
                })
                continue
            flush_tool_results()
            if role == "user":
                anthropic_messages.append({"role": "user", "content": message.get("content", "")})
                continue
            if role == "assistant":
                tool_calls = message.get("tool_calls") or []
                text_content = message.get("content") or ""
                if not isinstance(text_content, str):
                    text_content = json.dumps(text_content, ensure_ascii=False)
                if tool_calls:
                    blocks = []
                    if text_content:
                        blocks.append({"type": "text", "text": text_content})
                    for tc in tool_calls:
                        fn = tc.get("function") or {}
                        blocks.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": fn.get("name") or "",
                            "input": cls._parse_tool_arguments(fn.get("arguments")),
                        })
                    anthropic_messages.append({"role": "assistant", "content": blocks})
                else:
                    anthropic_messages.append({"role": "assistant", "content": text_content})
                continue
            raise ValueError(f"Anthropic 适配不支持的 message role: {role}")
        flush_tool_results()
        system = "\n\n".join(system_parts) if system_parts else None
        return system, anthropic_messages

    @staticmethod
    def _finalize_tool_use(slot: dict[str, Any]) -> ToolStreamEvent:
        arguments_raw = "".join(slot["input_parts"])
        try:
            arguments = json.loads(arguments_raw) if arguments_raw else {}
        except json.JSONDecodeError:
            arguments = {"_raw_arguments": arguments_raw}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        return ToolStreamEvent(
            kind="tool_call",
            tool_call=ToolCallFinished(
                tool_name=slot["name"] or "",
                call_id=slot["id"] or "",
                arguments=arguments,
            ),
        )

    def _anthropic_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _anthropic_complete_payload(self, messages, *, temperature: float) -> dict[str, Any]:
        system, converted = self.convert_messages(self._normalize_messages(messages))
        payload = {"model": self.config.model, "temperature": temperature, "messages": converted}
        if system:
            payload["system"] = system
        return payload

    def complete(self, messages, *, temperature=0.2, timeout_seconds=120, response_format_json=False, client=None) -> str:
        del response_format_json
        payload = self._anthropic_complete_payload(messages, temperature=temperature)
        url = self._join_url(self.config.base_url, "/messages")
        owns = client is None
        active = client or httpx.Client(timeout=timeout_seconds)
        raw_log = LLMRawLog(provider=self.config.provider, model=self.config.model, mode="complete")
        raw_log.request(url=url, payload=payload)
        try:
            response = active.post(url, headers=self._anthropic_headers(), json=payload)
            raw_log.raw_response(response.content, status_code=response.status_code)
            if response.status_code >= 400:
                raise LLMCompleteError(f"模型接口返回 HTTP {response.status_code}：{response.text[:500]}")
            body = response.json()
            raw_log.finish()
        except Exception as exc:
            raw_log.fail(exc)
            if not isinstance(exc, httpx.HTTPError):
                raise
            raise LLMCompleteError(f"模型接口连接失败：{exc}") from exc
        finally:
            if owns:
                active.close()
        if not isinstance(body, dict):
            raise LLMCompleteError("模型接口返回不是 JSON 对象")
        return extract_anthropic_text(body)

    async def stream_chat(self, messages, *, client=None, tools=None, raw_event_hook=None, tool_choice=None):
        normalized = self._normalize_messages(messages)
        system, chat_messages = self.convert_messages(normalized)
        payload: dict[str, Any] = {"model": self.config.model, "messages": chat_messages, "stream": True}
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = self.convert_tools(tools)
            if tool_choice is None or tool_choice == "auto":
                payload["tool_choice"] = {"type": "auto"}
            elif isinstance(tool_choice, str):
                payload["tool_choice"] = {"type": "tool", "name": tool_choice}
            else:
                payload["tool_choice"] = tool_choice
        headers = self._anthropic_headers()
        url = self._join_url(self.config.base_url, "/messages")
        owns_client = client is None
        active_client = client or httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
        pending: dict[int, dict[str, Any]] = {}
        raw_log = LLMRawLog(provider=self.config.provider, model=self.config.model, mode="stream")
        raw_log.request(url=url, payload=payload)
        try:
            async with active_client.stream("POST", url, headers=headers, json=payload) as response:
                await _raise_for_status_with_body(response, self.config)
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw_data = line[5:].strip()
                    if not raw_data or raw_data == "[DONE]":
                        continue
                    event = json.loads(raw_data)
                    event_type = event.get("type")
                    if event_type == "content_block_start":
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            idx = int(event.get("index", 0))
                            initial_input = block.get("input")
                            input_parts = []
                            if isinstance(initial_input, dict) and initial_input:
                                input_parts.append(json.dumps(initial_input, ensure_ascii=False))
                            pending[idx] = {"id": block.get("id"), "name": block.get("name"), "input_parts": input_parts}
                        continue
                    if event_type == "content_block_delta":
                        delta = event.get("delta") or {}
                        delta_type = delta.get("type")
                        if delta_type == "text_delta" and delta.get("text"):
                            yield ToolStreamEvent(kind="text", text=delta["text"])
                        elif delta_type == "input_json_delta":
                            slot = pending.get(int(event.get("index", 0)))
                            if slot is not None and delta.get("partial_json"):
                                slot["input_parts"].append(delta["partial_json"])
                        elif delta_type == "thinking_delta" and delta.get("thinking"):
                            yield ToolStreamEvent(kind="thinking", text=delta["thinking"])
                        continue
                    if event_type == "content_block_stop":
                        slot = pending.pop(int(event.get("index", 0)), None)
                        if slot is not None:
                            yield self._finalize_tool_use(slot)
                        continue
                    if event_type == "message_stop":
                        for idx in sorted(list(pending.keys())):
                            yield self._finalize_tool_use(pending.pop(idx))
            raw_log.finish()
        except Exception as exc:
            raw_log.fail(exc)
            raise
        finally:
            if owns_client:
                await active_client.aclose()


def _create_protocol_client(config: LLMModelConfig) -> LLMProtocolClient:
    if config.provider == "openai":
        return OpenAILLMClient(config)
    if config.provider == "anthropic":
        return AnthropicLLMClient(config)
    raise ValueError(f"不支持的 LLM provider: {config.provider}")


class BaseLLMProvider(LLMProtocolClient):
    def __init__(
        self,
        config: LLMModelConfig,
        fallback_config: LLMModelConfig | None = None,
        *,
        _client: LLMProtocolClient | None = None,
        _fallback_client: LLMProtocolClient | None = None,
    ) -> None:
        super().__init__(config)
        self.client = _client or _create_protocol_client(config)
        self.fallback_config = fallback_config
        self.fallback_client = _fallback_client or (
            _create_protocol_client(fallback_config) if fallback_config is not None else None
        )

    async def stream_chat(self, messages, *, client=None, tools=None, raw_event_hook=None, tool_choice=None):
        try:
            async for event in self.client.stream_chat(
                messages, client=client, tools=tools, raw_event_hook=raw_event_hook, tool_choice=tool_choice
            ):
                yield event
        except Exception as exc:
            if self.fallback_client is None:
                raise
            logger.warning(
                "主模型 %s 流式对话失败，切换 fallback %s: %s",
                self.config.name,
                self.fallback_config.name if self.fallback_config else "fallback",
                exc,
            )
            async for event in self.fallback_client.stream_chat(
                messages, client=client, tools=tools, raw_event_hook=raw_event_hook, tool_choice=tool_choice
            ):
                yield event

    def complete(self, messages, *, temperature=0.2, timeout_seconds=120, response_format_json=False, client=None) -> str:
        kwargs = dict(temperature=temperature, timeout_seconds=timeout_seconds, response_format_json=response_format_json, client=client)
        try:
            return self.client.complete(messages, **kwargs)
        except Exception as exc:
            if self.fallback_client is None:
                raise
            logger.warning("主模型 %s complete 失败，切换 fallback %s: %s", self.config.name, self.fallback_config.name if self.fallback_config else "fallback", exc)
            return self.fallback_client.complete(messages, **kwargs)


def create_provider(config: LLMModelConfig, fallback_config: LLMModelConfig | None = None) -> BaseLLMProvider:
    return BaseLLMProvider(config, fallback_config)
