"""渠道请求头经配置和基类传递，会话标识在发请求时解析。"""
import asyncio

import httpx
import pytest

from config import Settings, settings
from services.agents.supervisor import reset_context, set_context
from services.llm.factory import build_model_config
from services.llm.llm_service import BaseLLMProvider
from services.llm.llm_types import LLMModelConfig


def configured_provider():
    return BaseLLMProvider(LLMModelConfig(
        name="opencode-test", provider="openai", model="deepseek-v4.1-flash",
        base_url="https://opencode.ai/zen/go/v1", api_key="test-key",
        extra_headers={"User-Agent": "novel/1.0", "x-opencode-session": "{session_id}"},
    ))


def test_headers_survive_config_and_factory(monkeypatch):
    config = Settings()
    config._parse_llm_config({"llm": [{"test": {
        "base_url": "https://example.test", "api_key": "key",
        "extra_headers": {"User-Agent": "novel/1.0"},
    }}]})
    monkeypatch.setattr(settings, "_models", config._models)
    assert build_model_config("test").extra_headers == {"User-Agent": "novel/1.0"}


def test_complete_sends_configured_headers_and_current_session():
    seen = []

    def handle(request):
        seen.append(dict(request.headers))
        assert "extra_headers" not in request.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    provider = configured_provider()
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        for session_id in ["session-a", "session-a", "session-b"]:
            token = set_context({"session_id": session_id})
            try:
                assert provider.complete([{"role": "user", "content": "hi"}], client=client) == "OK"
            finally:
                reset_context(token)
    assert [h["x-opencode-session"] for h in seen] == ["session-a", "session-a", "session-b"]
    assert all(h["user-agent"] == "novel/1.0" for h in seen)
    assert all(h["authorization"] == "Bearer test-key" for h in seen)


def test_concurrent_streams_keep_sessions_isolated():
    seen = []

    def handle(request):
        seen.append(request.headers["x-opencode-session"])
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n')

    provider = configured_provider()

    async def run(session_id):
        token = set_context({"session_id": session_id})
        try:
            await asyncio.sleep(0)
            async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
                events = [e async for e in provider.stream_chat(
                    [{"role": "user", "content": "hi"}], client=client)]
                assert any(e.text == "OK" for e in events)
        finally:
            reset_context(token)

    async def both():
        await asyncio.gather(run("session-a"), run("session-b"))

    asyncio.run(both())
    assert sorted(seen) == ["session-a", "session-b"]


def test_session_template_requires_real_session():
    token = set_context({})
    try:
        with pytest.raises(ValueError, match="session_id"):
            configured_provider().client._openai_headers()
    finally:
        reset_context(token)


def test_other_channels_need_no_session():
    provider = BaseLLMProvider(LLMModelConfig(
        name="other", provider="openai", model="other",
        base_url="https://example.test/v1", api_key="key"))
    assert provider.client._openai_headers() == {
        "Authorization": "Bearer key", "Content-Type": "application/json"}
