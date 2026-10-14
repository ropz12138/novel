"""Haiku 的显式输出上限通过既有模型配置传递。"""
import asyncio

from services.llm.factory import build_model_config
from services.llm.llm_service import AnthropicLLMClient, _create_protocol_client


def test_haiku_complete_payload_has_32k_output_limit():
    model = build_model_config("claude-haiku-5-5")
    assert model.provider == "anthropic"
    assert isinstance(_create_protocol_client(model), AnthropicLLMClient)
    payload = AnthropicLLMClient(model)._anthropic_complete_payload(
        [{"role": "user", "content": "你好"}],
        temperature=0.2,
    )
    assert payload["max_tokens"] == 32768


def test_haiku_stream_payload_has_32k_output_limit():
    from test_llm_base import _FakeAsyncClient

    seen = []

    class Client(_FakeAsyncClient):
        def stream(self, *args, **kwargs):
            assert args[1] == "https://www.micuapi.ai/v1/messages"
            assert "x-api-key" in kwargs["headers"]
            assert "Authorization" not in kwargs["headers"]
            seen.append(kwargs["json"])
            return super().stream(*args, **kwargs)

    async def run():
        protocol = AnthropicLLMClient(build_model_config("claude-haiku-5-5"))
        async for _ in protocol.stream_chat(
            [{"role": "user", "content": "你好"}],
            client=Client(["data: [DONE]"]),
            tools=[{"type": "function", "function": {
                "name": "submit_review", "parameters": {"type": "object", "properties": {}}
            }}],
        ):
            pass

    asyncio.run(run())
    assert seen[0]["max_tokens"] == 32768
    assert seen[0]["tool_choice"] == {"type": "auto"}
    assert seen[0]["tools"][0]["name"] == "submit_review"
    assert "input_schema" in seen[0]["tools"][0]


def test_anthropic_complete_copies_extra_body():
    from services.llm.llm_types import LLMModelConfig

    model = LLMModelConfig(name="test", base_url="http://test", api_key="test",
                           provider="anthropic", model="test",
                           extra_body={"max_tokens": 32768, "metadata": {"user_id": "test"}})
    payload = AnthropicLLMClient(model)._anthropic_complete_payload(
        [{"role": "user", "content": "你好"}], temperature=0.2,
    )
    payload["metadata"]["user_id"] = "changed"
    assert model.extra_body["metadata"]["user_id"] == "test"
