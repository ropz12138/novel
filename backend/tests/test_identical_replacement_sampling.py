"""old 与 new 完全相同时，只改下一次 agent 请求的采样参数。"""
import asyncio
import json

import database
from services.agents import supervisor as supervisor_mod
from services.agents.sampling_override import (
    arm_identical_replacement_sampling,
    sampling_override_for_model,
    supervisor_sampling_scope,
)
from services.agents.tools import node_tools as nt
from services.llm.langchain_adapter import NovelLLM
from services.llm.llm_service import create_provider
from services.llm.llm_types import LLMModelConfig
from services.thinking_llm import FallbackLLM
from tests.test_update_node_content_edit import _seed_chapter


def test_sampling_override_matches_model_family():
    assert sampling_override_for_model("deepseek-flash") == {"temperature": 2}
    assert sampling_override_for_model("glm-5.3-flash") == {"top_p": 1}
    assert sampling_override_for_model("mimo-v2.6-flash") == {"temperature": 1.5}
    assert sampling_override_for_model("qwen3.8-flash") == {"temperature": 1.8}
    assert sampling_override_for_model("gpt-6-sol") == {"temperature": 2}
    assert sampling_override_for_model("gemini-3.8-flash-high") == {"temperature": 2}


def test_sampling_override_rejects_unknown_model():
    try:
        sampling_override_for_model("other-model")
    except ValueError as exc:
        assert "other-model" in str(exc)
    else:
        raise AssertionError("未知模型应拒绝设置采样参数")


def test_identical_old_new_arms_next_request_only():
    db = database.SessionLocal()
    token = supervisor_mod.set_context({"work_id": "sampling-work"})
    try:
        node, _original = _seed_chapter(db, "arm-identical")
        identical = json.loads(nt._update_node_sync(
            node.id,
            mode="replace",
            replacements=[{"old": "就你理性", "new": "就你理性"}],
        ))
        assert "old 和 new 完全相同" in identical["error"]
        assert supervisor_mod.get_context()["identical_replacement_sampling"] is True

        supervisor_mod.get_context()["identical_replacement_sampling"] = False
        missing = json.loads(nt._update_node_sync(
            node.id,
            mode="replace",
            replacements=[{"old": "正文里没有", "new": "改后"}],
        ))
        assert "未找到" in missing["error"]
        assert supervisor_mod.get_context()["identical_replacement_sampling"] is False
    finally:
        supervisor_mod.reset_context(token)
        db.close()


def test_successful_replace_does_not_arm_sampling():
    db = database.SessionLocal()
    token = supervisor_mod.set_context({"work_id": "sampling-work"})
    try:
        node, _original = _seed_chapter(db, "arm-success")
        result = json.loads(nt._update_node_sync(
            node.id,
            mode="replace",
            replacements=[{"old": "就你理性", "new": "就你能耐"}],
        ))
        assert result["success"] is True
        assert "identical_replacement_sampling" not in supervisor_mod.get_context()
    finally:
        supervisor_mod.reset_context(token)
        db.close()


class _RecordingClient:
    def __init__(self):
        self.payloads = []

    def stream(self, *args, **kwargs):
        self.payloads.append(kwargs["json"])
        return _DoneResponse()

    async def aclose(self):
        return None


class _DoneResponse:
    status_code = 200
    is_success = True
    request = type("Req", (), {"url": "http://example.test/v1/chat/completions"})()

    async def aread(self):
        return b""

    async def aiter_lines(self):
        yield "data: [DONE]"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def _llm(name: str, extra_body: dict) -> NovelLLM:
    config = LLMModelConfig(
        name=name,
        base_url="http://example.test/v1",
        api_key="k",
        provider="openai",
        model=name,
        extra_body=dict(extra_body),
    )
    return NovelLLM(provider=create_provider(config), model_name=name)


def _stream(llm: NovelLLM, client: _RecordingClient):
    async def _run():
        async for _event in llm.provider.stream_chat(
            [{"role": "user", "content": "hi"}],
            client=client,
        ):
            pass

    asyncio.run(_run())


def test_scope_changes_only_the_next_stream_payload():
    deepseek = _llm("deepseek-flash", {"temperature": 0.5, "thinking": {"type": "disabled"}})
    glm = _llm("glm-5.3-flash", {"temperature": 0.5, "reasoning_effort": "low"})
    mimo = _llm("mimo-v2.6-flash", {"temperature": 0.5, "thinking": {"type": "enabled"}})
    active = FallbackLLM(glm, FallbackLLM(deepseek, mimo))
    token = supervisor_mod.set_context({"work_id": "sampling-work"})
    first = _RecordingClient()
    second = _RecordingClient()
    try:
        arm_identical_replacement_sampling()
        with supervisor_sampling_scope(active):
            _stream(deepseek, first)
            _stream(glm, first)
            _stream(mimo, first)
        _stream(deepseek, second)
        assert first.payloads[0]["temperature"] == 2
        assert first.payloads[0]["thinking"] == {"type": "disabled"}
        assert first.payloads[1]["top_p"] == 1
        assert first.payloads[1]["temperature"] == 0.5
        assert first.payloads[1]["reasoning_effort"] == "low"
        assert first.payloads[2]["temperature"] == 1.5
        assert first.payloads[2]["thinking"] == {"type": "enabled"}
        assert second.payloads[0]["temperature"] == 0.5
        assert "top_p" not in second.payloads[0]
        assert deepseek.provider.client.config.extra_body["temperature"] == 0.5
        assert "top_p" not in glm.provider.client.config.extra_body
    finally:
        supervisor_mod.reset_context(token)
