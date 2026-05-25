"""测试 tool-call arguments JSON 修复逻辑

验证：
1. repair_tool_call_arguments 能修复字符串值内未转义的双引号
2. _create_chat_result 在解析失败时调用修复逻辑
3. 修复失败时直接抛出异常，不做兜底
"""

import json
import sys

import pytest

sys.path.insert(0, "/root/Novel/backend")


class TestRepairToolCallArguments:
    """验证 repair_tool_call_arguments 修复函数"""

    def test_valid_json_passes_through(self):
        from app.core.deepseek_llm import repair_tool_call_arguments

        original = '{"name": "张三", "age": 25}'
        result = repair_tool_call_arguments(original)
        assert json.loads(result) == {"name": "张三", "age": 25}

    def test_fixes_unescaped_double_quotes_in_string_values(self):
        from app.core.deepseek_llm import repair_tool_call_arguments

        # 字符串值内出现了英文双引号
        broken = '{"personality": "他说"你好"然后离开了", "name": "张三"}'
        result = repair_tool_call_arguments(broken)
        parsed = json.loads(result)
        assert parsed["name"] == "张三"
        assert "你好" in parsed["personality"]

    def test_fixes_multiple_unescaped_quotes(self):
        from app.core.deepseek_llm import repair_tool_call_arguments

        broken = '{"desc": "她"笑了"一下，然后说"好的"", "name": "李四"}'
        result = repair_tool_call_arguments(broken)
        parsed = json.loads(result)
        assert parsed["name"] == "李四"
        assert "笑了" in parsed["desc"]
        assert "好的" in parsed["desc"]

    def test_handles_already_escaped_quotes(self):
        from app.core.deepseek_llm import repair_tool_call_arguments

        original = '{"desc": "他说\\\"你好\\\"然后离开了"}'
        result = repair_tool_call_arguments(original)
        parsed = json.loads(result)
        assert parsed["desc"] == '他说"你好"然后离开了'

    def test_raises_on_truly_broken_json(self):
        from app.core.deepseek_llm import repair_tool_call_arguments

        # 根本不是 JSON
        with pytest.raises(ValueError):
            repair_tool_call_arguments("not json at all {{{{")

    def test_preserves_list_and_nested_structures(self):
        from app.core.deepseek_llm import repair_tool_call_arguments

        original = '{"items": ["a", "b"], "count": 2}'
        result = repair_tool_call_arguments(original)
        parsed = json.loads(result)
        assert parsed["items"] == ["a", "b"]
        assert parsed["count"] == 2

    def test_fixes_quotes_in_list_string_values(self):
        from app.core.deepseek_llm import repair_tool_call_arguments

        broken = '{"characters": [{"name": "王五", "personality": "喜欢说"不""}]}'
        result = repair_tool_call_arguments(broken)
        parsed = json.loads(result)
        assert parsed["characters"][0]["name"] == "王五"
        assert "不" in parsed["characters"][0]["personality"]


class TestCreateChatResultWithRepair:
    """验证 _create_chat_result 在 tool_call arguments 解析失败时尝试修复"""

    def _make_response_with_broken_tool_call(self, broken_args: str):
        """构造一个包含 tool_call 的 API 响应 dict"""
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {
                                    "name": "submit_character_details",
                                    "arguments": broken_args,
                                },
                            }
                        ],
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            "model": "deepseek-v4-pro",
        }

    def test_valid_tool_call_passes_through(self):
        from app.core.deepseek_llm import DeepSeekChatOpenAI

        llm = DeepSeekChatOpenAI(
            model="deepseek-v4-pro",
            api_key="sk-test",
            base_url="https://api.deepseek.com",
        )
        response = self._make_response_with_broken_tool_call(
            '{"characters": [{"name": "张三"}]}'
        )
        result = llm._create_chat_result(response)
        msg = result.generations[0].message
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "submit_character_details"
        assert msg.tool_calls[0]["args"]["characters"][0]["name"] == "张三"

    def test_broken_tool_call_gets_repaired(self):
        from app.core.deepseek_llm import DeepSeekChatOpenAI

        llm = DeepSeekChatOpenAI(
            model="deepseek-v4-pro",
            api_key="sk-test",
            base_url="https://api.deepseek.com",
        )
        # 字符串值内嵌未转义双引号
        response = self._make_response_with_broken_tool_call(
            '{"characters": [{"name": "张三", "personality": "他说"你好"就走"}]}'
        )
        result = llm._create_chat_result(response)
        msg = result.generations[0].message
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["args"]["characters"][0]["name"] == "张三"

    def test_truly_broken_tool_call_produces_invalid_tool_calls(self):
        """彻底无法修复的 JSON 会产生 invalid_tool_calls（LangChain 行为），
        下游 _parse_section_from_tool_call 遍历 tool_calls 为空时会报错。"""
        from app.core.deepseek_llm import DeepSeekChatOpenAI

        llm = DeepSeekChatOpenAI(
            model="deepseek-v4-pro",
            api_key="sk-test",
            base_url="https://api.deepseek.com",
        )
        # 根本无法修复的 JSON
        response = self._make_response_with_broken_tool_call("{{{{not json")
        result = llm._create_chat_result(response)
        msg = result.generations[0].message
        # LangChain 会把解析失败的 tool_call 放到 invalid_tool_calls
        assert len(msg.invalid_tool_calls) == 1
        assert len(msg.tool_calls) == 0


class TestOutlinePromptQuoteConstraint:
    """验证大纲生成 prompt 中包含引号约束"""

    def test_submit_character_details_prompt_has_quote_constraint(self):
        import inspect

        from app.services.work_service import WorkService

        source = inspect.getsource(WorkService._generate_outline_sections)
        assert "_QUOTE_CONSTRAINT" in source, (
            "大纲生成 prompt 应引用 _QUOTE_CONSTRAINT 引号约束常量"
        )
