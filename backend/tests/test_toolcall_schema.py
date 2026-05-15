"""Tests for _normalize_operation_args and ToolCall schema."""
import sys
sys.path.insert(0, "/root/Novel/backend")

from app.schemas.work_schema import ToolCall, ChatEditResponse
from app.services.work_service import _normalize_operation_args


class TestNormalizeOperationArgs:
    # --- Flat top-level format ---
    def test_flat_update_character(self):
        ops = [{"tool": "update_character", "name": "嬴萧", "fields": {"gender": "女"}}]
        result = _normalize_operation_args(ops)
        assert result[0]["args"]["name"] == "嬴萧"
        assert result[0]["args"]["fields"] == {"gender": "女"}

    def test_flat_add_timeline(self):
        ops = [{"tool": "add_timeline_node", "order": 1, "development_node": "test", "time_node": "phase1"}]
        result = _normalize_operation_args(ops)
        assert result[0]["args"]["order"] == 1
        assert result[0]["args"]["development_node"] == "test"

    def test_flat_delete_character(self):
        ops = [{"tool": "delete_character", "name": "嬴萧"}]
        result = _normalize_operation_args(ops)
        assert result[0]["args"]["name"] == "嬴萧"

    # --- "arguments" instead of "args" ---
    def test_arguments_key_instead_of_args(self):
        """LLM uses 'arguments' instead of 'args'."""
        ops = [{"tool": "update_character", "arguments": {"name": "林萧", "fields": {"name": "嬴萧"}}}]
        result = _normalize_operation_args(ops)
        assert result[0]["args"]["name"] == "林萧"
        assert result[0]["args"]["fields"] == {"name": "嬴萧"}

    # --- Extra nesting: {"args": {"parameters": {...}}} ---
    def test_nested_parameters_key(self):
        """LLM wraps args inside a 'parameters' key."""
        ops = [{"tool": "update_character", "args": {"parameters": {"name": "林萧", "fields": {"name": "嬴萧"}}}}]
        result = _normalize_operation_args(ops)
        assert result[0]["args"]["name"] == "林萧"
        assert result[0]["args"]["fields"] == {"name": "嬴萧"}

    # --- Already correct format ---
    def test_already_nested_args(self):
        ops = [{"tool": "update_character", "args": {"name": "嬴萧", "fields": {"gender": "女"}}}]
        result = _normalize_operation_args(ops)
        assert result[0]["args"]["name"] == "嬴萧"
        assert result[0]["args"]["fields"] == {"gender": "女"}

    def test_empty_ops(self):
        assert _normalize_operation_args([]) == []

    def test_args_empty_dict(self):
        ops = [{"tool": "delete_node", "args": {}}]
        result = _normalize_operation_args(ops)
        assert result[0]["args"] == {}

    def test_mixed_flat_and_nested(self):
        ops = [
            {"tool": "add_timeline_node", "order": 1, "development_node": "test"},
            {"tool": "update_character", "args": {"name": "嬴萧", "fields": {"age": "20"}}},
        ]
        result = _normalize_operation_args(ops)
        assert result[0]["args"]["order"] == 1
        assert result[1]["args"]["name"] == "嬴萧"

    # --- Real-world scenarios from actual LLM output ---
    def test_real_llm_format_with_parameters(self):
        """Exact LLM output: args.parameters wrap."""
        ops = [{"tool": "update_character", "args": {"parameters": {"name": "林萧", "fields": {"name": "嬴萧"}}}}]
        result = _normalize_operation_args(ops)
        assert result[0]["args"]["name"] == "林萧"
        assert result[0]["args"]["fields"]["name"] == "嬴萧"

    def test_real_llm_format_with_arguments(self):
        """Exact LLM output: 'arguments' instead of 'args'."""
        ops = [{"tool": "update_character", "arguments": {"name": "林萧", "fields": {"name": "嬴萧"}}}]
        result = _normalize_operation_args(ops)
        assert result[0]["args"]["name"] == "林萧"
        assert result[0]["args"]["fields"]["name"] == "嬴萧"


class TestToolCallSchema:
    def test_normal_with_args(self):
        tc = ToolCall(tool="update_character", args={"name": "嬴萧", "fields": {"gender": "女"}})
        assert tc.tool == "update_character"
        assert tc.args == {"name": "嬴萧", "fields": {"gender": "女"}}

    def test_llm_flat_format(self):
        raw = {"tool": "update_character", "name": "嬴萧", "fields": {"gender": "女"}}
        tc = ToolCall.model_validate(raw)
        assert tc.args["name"] == "嬴萧"

    def test_chat_edit_response_with_flat_operations(self):
        raw = {
            "assistant_message": "已修改角色",
            "operations": [
                {"tool": "update_character", "name": "嬴萧", "fields": {"gender": "女"}},
            ],
            "outline_tree": {"story": {"title": "test"}},
        }
        resp = ChatEditResponse.model_validate(raw)
        assert resp.operations[0].args["name"] == "嬴萧"
