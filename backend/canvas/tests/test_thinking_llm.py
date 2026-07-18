"""Thinking Mode reasoning_content 解析测试 — TDD。"""
from langchain_core.messages import AIMessage, AIMessageChunk

from app.services.thinking_llm import (
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
