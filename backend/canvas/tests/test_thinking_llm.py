"""Thinking Mode reasoning_content 解析测试 — TDD。"""
import asyncio

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.tools import tool as lc_tool

from app.config import Settings
from app.services.thinking_llm import (
    FallbackLLM,
    ThinkingChatOpenAI,
    thinking_convert_delta_to_message_chunk,
    thinking_convert_dict_to_message,
    thinking_convert_message_to_dict,
)


def test_thinking_convert_delta_to_message_chunk():
    chunk = thinking_convert_delta_to_message_chunk(
        {"content": None, "reasoning_content": "分析用户需求"},
        AIMessageChunk,
    )
    assert isinstance(chunk, AIMessageChunk)
    assert chunk.additional_kwargs.get("reasoning_content") == "分析用户需求"


def test_thinking_convert_dict_to_message():
    msg = thinking_convert_dict_to_message({
        "role": "assistant",
        "content": "好的",
        "reasoning_content": "先理解意图",
    })
    assert isinstance(msg, AIMessage)
    assert msg.additional_kwargs.get("reasoning_content") == "先理解意图"


def test_thinking_convert_message_to_dict_roundtrip():
    ai = AIMessage(
        content="回复",
        additional_kwargs={"reasoning_content": "推理过程"},
    )
    payload = thinking_convert_message_to_dict(ai)
    assert payload.get("reasoning_content") == "推理过程"


def test_thinking_chat_openai_class_exists():
    assert issubclass(ThinkingChatOpenAI, object)


# --------------------------------------------------------------------------- #
# FallbackLLM：主模型任意业务报错都切备用模型；仅排除系统级异常
# --------------------------------------------------------------------------- #


class FakeLLM:
    """可配置返回值/抛出异常的 LLM 替身，覆盖 invoke/ainvoke/stream/astream。"""

    def __init__(
        self,
        model_name: str = "fake",
        *,
        invoke_ret=None,
        invoke_exc=None,
        ainvoke_ret=None,
        ainvoke_exc=None,
        stream_chunks=None,
        stream_exc=None,
        stream_before=0,
        astream_chunks=None,
        astream_exc=None,
        astream_before=0,
    ):
        self.model_name = model_name
        self.invoke_ret = invoke_ret
        self.invoke_exc = invoke_exc
        self.ainvoke_ret = ainvoke_ret
        self.ainvoke_exc = ainvoke_exc
        self.stream_chunks = list(stream_chunks or [])
        self.stream_exc = stream_exc
        self.stream_before = stream_before
        self.astream_chunks = list(astream_chunks or [])
        self.astream_exc = astream_exc
        self.astream_before = astream_before

    def invoke(self, input, config=None, **kwargs):
        if self.invoke_exc is not None:
            raise self.invoke_exc
        return self.invoke_ret

    async def ainvoke(self, input, config=None, **kwargs):
        if self.ainvoke_exc is not None:
            raise self.ainvoke_exc
        return self.ainvoke_ret

    def stream(self, input, config=None, **kwargs):
        for i, c in enumerate(self.stream_chunks):
            if self.stream_exc is not None and i >= self.stream_before:
                raise self.stream_exc
            yield c
        if self.stream_exc is not None and len(self.stream_chunks) <= self.stream_before:
            raise self.stream_exc

    async def astream(self, input, config=None, **kwargs):
        for i, c in enumerate(self.astream_chunks):
            if self.astream_exc is not None and i >= self.astream_before:
                raise self.astream_exc
            yield c
        if self.astream_exc is not None and len(self.astream_chunks) <= self.astream_before:
            raise self.astream_exc


BUSINESS_ERRORS = [
    ValueError("boom"),
    ConnectionError("reset by peer"),
    RuntimeError("upstream 500"),
    Exception("429 Too Many Requests"),
]
# 直接调用（invoke/ainvoke）下可复现的全部系统级异常
SYSTEM_ERRORS = [KeyboardInterrupt(), asyncio.CancelledError(), GeneratorExit()]
# 生成器方法（stream/astream）：GeneratorExit 主动 raise 会被解释器按「生成器关闭」语义
# 转成 StopIteration，无法用此方式复现，故生成器场景仅覆盖可稳定传播的两类
SYSTEM_ERRORS_STREAM = [KeyboardInterrupt(), asyncio.CancelledError()]


# --- invoke ---


def test_invoke_returns_primary_result_when_ok():
    primary = FakeLLM("p", invoke_ret="OK")
    fallback = FakeLLM("f", invoke_ret="FALLBACK")
    assert FallbackLLM(primary, fallback).invoke("x") == "OK"


@pytest.mark.parametrize("exc", BUSINESS_ERRORS)
def test_invoke_falls_back_on_any_business_error(exc):
    primary = FakeLLM("p", invoke_exc=exc)
    fallback = FakeLLM("f", invoke_ret="FALLBACK")
    assert FallbackLLM(primary, fallback).invoke("x") == "FALLBACK"


@pytest.mark.parametrize("exc", SYSTEM_ERRORS)
def test_invoke_reraises_system_errors(exc):
    primary = FakeLLM("p", invoke_exc=exc)
    fallback = FakeLLM("f", invoke_ret="FALLBACK")
    with pytest.raises(type(exc)):
        FallbackLLM(primary, fallback).invoke("x")


# --- ainvoke ---


def test_ainvoke_returns_primary_result_when_ok():
    primary = FakeLLM("p", ainvoke_ret="OK")
    fallback = FakeLLM("f", ainvoke_ret="FALLBACK")

    async def _run():
        return await FallbackLLM(primary, fallback).ainvoke("x")

    assert asyncio.run(_run()) == "OK"


@pytest.mark.parametrize("exc", BUSINESS_ERRORS)
def test_ainvoke_falls_back_on_any_business_error(exc):
    primary = FakeLLM("p", ainvoke_exc=exc)
    fallback = FakeLLM("f", ainvoke_ret="FALLBACK")

    async def _run():
        return await FallbackLLM(primary, fallback).ainvoke("x")

    assert asyncio.run(_run()) == "FALLBACK"


@pytest.mark.parametrize("exc", SYSTEM_ERRORS)
def test_ainvoke_reraises_system_errors(exc):
    primary = FakeLLM("p", ainvoke_exc=exc)
    fallback = FakeLLM("f", ainvoke_ret="FALLBACK")

    async def _run():
        return await FallbackLLM(primary, fallback).ainvoke("x")

    with pytest.raises(type(exc)):
        asyncio.run(_run())


# --- stream ---


def test_stream_returns_primary_chunks_when_ok():
    primary = FakeLLM("p", stream_chunks=["A", "B"])
    fallback = FakeLLM("f", stream_chunks=["X"])
    assert list(FallbackLLM(primary, fallback).stream("x")) == ["A", "B"]


def test_stream_falls_back_from_start_on_mid_stream_error():
    # 主模型吐出 A、B 后中途断流 → 备用从头补 X、Y（接受前缀重复）
    primary = FakeLLM(
        "p", stream_chunks=["A", "B", "C"], stream_exc=ConnectionError("drop"), stream_before=2
    )
    fallback = FakeLLM("f", stream_chunks=["X", "Y"])
    assert list(FallbackLLM(primary, fallback).stream("x")) == ["A", "B", "X", "Y"]


def test_stream_falls_back_when_error_before_any_chunk():
    primary = FakeLLM("p", stream_chunks=["A", "B"], stream_exc=RuntimeError("500"), stream_before=0)
    fallback = FakeLLM("f", stream_chunks=["X", "Y"])
    assert list(FallbackLLM(primary, fallback).stream("x")) == ["X", "Y"]


@pytest.mark.parametrize("exc", SYSTEM_ERRORS_STREAM)
def test_stream_reraises_system_errors(exc):
    primary = FakeLLM("p", stream_chunks=["A"], stream_exc=exc, stream_before=0)
    fallback = FakeLLM("f", stream_chunks=["X"])
    with pytest.raises(type(exc)):
        list(FallbackLLM(primary, fallback).stream("x"))


# --- astream ---


def test_astream_falls_back_from_start_on_mid_stream_error():
    primary = FakeLLM(
        "p", astream_chunks=["A", "B", "C"], astream_exc=ValueError("boom"), astream_before=2
    )
    fallback = FakeLLM("f", astream_chunks=["X", "Y"])
    fb = FallbackLLM(primary, fallback)

    async def _run():
        out = []
        async for c in fb.astream("x"):
            out.append(c)
        return out

    assert asyncio.run(_run()) == ["A", "B", "X", "Y"]


@pytest.mark.parametrize("exc", SYSTEM_ERRORS_STREAM)
def test_astream_reraises_system_errors(exc):
    primary = FakeLLM("p", astream_chunks=["A"], astream_exc=exc, astream_before=0)
    fallback = FakeLLM("f", astream_chunks=["X"])
    fb = FallbackLLM(primary, fallback)

    async def _run():
        out = []
        async for c in fb.astream("x"):
            out.append(c)
        return out

    with pytest.raises(type(exc)):
        asyncio.run(_run())


# --------------------------------------------------------------------------- #
# extra_body 从 config 读 → get_llm 传播 → bind_tools 使用
# --------------------------------------------------------------------------- #


@lc_tool
def _sample_tool(text: str) -> str:
    """示例工具"""
    return text


def _make_llm():
    return ThinkingChatOpenAI(model="x", base_url="http://x", api_key="x")


# --- config.py 解析 extra_body ---


def test_parse_llm_config_reads_extra_body():
    s = Settings.__new__(Settings)
    s._parse_llm_config({"llm": [
        {"model-a": {"base_url": "u", "api_key": "k",
                     "extra_body": {"thinking": {"type": "adaptive"}}}},
        {"model-b": {"base_url": "u", "api_key": "k"}},  # 不配
    ]})
    assert s._models["model-a"]["extra_body"] == {"thinking": {"type": "adaptive"}}
    assert s._models["model-b"]["extra_body"] is None


def test_get_model_config_exposes_extra_body():
    s = Settings.__new__(Settings)
    s._parse_llm_config({"llm": [
        {"model-a": {"base_url": "u", "api_key": "k",
                     "extra_body": {"thinking": {"type": "adaptive"}}}},
    ]})
    assert s.get_model_config("model-a")["extra_body"] == {"thinking": {"type": "adaptive"}}


# --- ThinkingChatOpenAI.bind_tools 用实例 extra_body ---


def test_bind_tools_uses_instance_extra_body():
    llm = _make_llm()
    llm._extra_body = {"thinking": {"type": "adaptive"}}
    bound = llm.bind_tools([_sample_tool])
    assert bound.kwargs.get("extra_body") == {"thinking": {"type": "adaptive"}}


def test_bind_tools_injects_nothing_when_extra_body_unset():
    llm = _make_llm()
    bound = llm.bind_tools([_sample_tool])
    eb = bound.kwargs.get("extra_body")
    # 不应注入任何 thinking 参数
    assert not (eb and eb.get("thinking"))


def test_bind_tools_caller_extra_body_wins():
    llm = _make_llm()
    llm._extra_body = {"thinking": {"type": "adaptive"}}
    bound = llm.bind_tools([_sample_tool], extra_body={"thinking": {"type": "disabled"}})
    assert bound.kwargs.get("extra_body") == {"thinking": {"type": "disabled"}}


# --- get_llm 把 config 的 extra_body 传播到实例 ---


def test_get_llm_propagates_extra_body(monkeypatch):
    from app.services.agents import llm as llm_mod

    monkeypatch.setattr(llm_mod.settings, "default_model", "m", raising=False)
    monkeypatch.setattr(llm_mod.settings, "fallback_model", "", raising=False)
    monkeypatch.setattr(
        llm_mod.settings, "get_model_config",
        lambda name=None: {"base_url": "http://x", "api_key": "k",
                           "extra_body": {"thinking": {"type": "adaptive"}}},
    )
    llm = llm_mod.get_llm(primary="m")
    primary = getattr(llm, "_primary", llm)
    assert primary._extra_body == {"thinking": {"type": "adaptive"}}


def test_get_llm_propagates_extra_body_to_fallback(monkeypatch):
    from app.services.agents import llm as llm_mod

    monkeypatch.setattr(llm_mod.settings, "default_model", "p", raising=False)
    monkeypatch.setattr(llm_mod.settings, "fallback_model", "f", raising=False)
    monkeypatch.setattr(
        llm_mod.settings, "get_model_config",
        lambda name=None: {
            "base_url": "http://x", "api_key": "k",
            "extra_body": {"thinking": {"type": "enabled"}} if name == "p"
            else {"thinking": {"type": "adaptive"}},
        },
    )
    fb = llm_mod.get_llm(primary="p", fallback="f")
    assert fb._primary._extra_body == {"thinking": {"type": "enabled"}}
    assert fb._fallback._extra_body == {"thinking": {"type": "adaptive"}}
