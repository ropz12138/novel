"""删除未调用代码后：这些符号不得再出现在生产模块中。"""
import importlib

import pytest


def test_llm_chat_service_is_removed():
    mod = importlib.import_module("services.llm.llm_service")
    assert not hasattr(mod, "LLMChatService")
    assert not hasattr(mod, "create_llm_chat_service")


def test_base_provider_has_no_unused_complete_helpers():
    from services.llm.llm_service import BaseLLMProvider, LLMProtocolClient

    for name in (
        "complete_json",
        "acomplete_json",
        "complete_vision",
        "acomplete",
        "acomplete_batch",
        "acomplete_json_batch",
    ):
        assert not hasattr(BaseLLMProvider, name)
        assert name not in LLMProtocolClient.__dict__


def test_llm_tool_loop_types_are_removed():
    from services.llm import llm_tool

    for name in ("ToolRegistry", "ToolLoopEvent", "ToolCallResult", "build_tool_error_result"):
        assert not hasattr(llm_tool, name)


def test_chat_message_type_is_removed():
    from services.llm import llm_types

    assert not hasattr(llm_types, "ChatMessage")


def test_parse_json_object_is_removed():
    from services.llm import llm_complete_utils

    assert not hasattr(llm_complete_utils, "parse_json_object")


def test_thinking_chat_openai_is_removed():
    from services import thinking_llm

    assert not hasattr(thinking_llm, "ThinkingChatOpenAI")
    assert not hasattr(thinking_llm, "thinking_convert_message_to_dict")
    assert not hasattr(thinking_llm, "repair_tool_call_arguments")


def test_chapter_context_service_module_is_removed():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("services.chapter_context_service")


def test_llm_package_does_not_export_dead_api():
    from services import llm as llm_pkg

    for name in ("LLMChatService", "create_llm_chat_service", "ChatMessage"):
        assert name not in llm_pkg.__all__
        assert not hasattr(llm_pkg, name)


def test_protocol_client_complete_and_stream_remain():
    from services.llm.llm_service import LLMProtocolClient

    assert hasattr(LLMProtocolClient, "complete")
    assert hasattr(LLMProtocolClient, "stream_chat")
