"""测试 8 个独立大纲/角色工具的注册、schema 和 coroutine 逻辑。

覆盖：
1. 工具注册 — _OUTLINE_CORE_TOOLS 包含新的 generate_character_details 和 edit_character_details
2. Input Schema — 新增的 GenerateCharacterDetailsInput 和 EditCharacterDetailsInput 验证
3. _extract_tool_call_args 辅助函数
4. _invoke_and_persist — LLM 调用+入库辅助函数（mock LLM）
5. generate_macro_outline coroutine — 独立 LLM 交互
6. generate_meso_outline coroutine
7. generate_micro_outline coroutine
8. generate_character_details coroutine
9. edit_macro_outline coroutine
10. edit_meso_outline coroutine
11. edit_micro_outline coroutine
12. edit_character_details coroutine
13. 旧工具标记为 deprecated
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from pydantic import ValidationError


# ── 工具注册 ──


class TestToolRegistration:
    def test_core_tools_contains_new_generate_character_details(self):
        from app.services.supervisor.outline_tools import _OUTLINE_CORE_TOOLS
        names = [t.name for t in _OUTLINE_CORE_TOOLS]
        assert "generate_character_details" in names

    def test_core_tools_contains_new_edit_character_details(self):
        from app.services.supervisor.outline_tools import _OUTLINE_CORE_TOOLS
        names = [t.name for t in _OUTLINE_CORE_TOOLS]
        assert "edit_character_details" in names

    def test_core_tools_contains_generate_macro_meso_micro(self):
        from app.services.supervisor.outline_tools import _OUTLINE_CORE_TOOLS
        names = [t.name for t in _OUTLINE_CORE_TOOLS]
        for expected in ("generate_macro_outline", "generate_meso_outline", "generate_micro_outline"):
            assert expected in names

    def test_core_tools_contains_edit_macro_meso_micro(self):
        from app.services.supervisor.outline_tools import _OUTLINE_CORE_TOOLS
        names = [t.name for t in _OUTLINE_CORE_TOOLS]
        for expected in ("edit_macro_outline", "edit_meso_outline", "edit_micro_outline"):
            assert expected in names

    def test_core_tools_count(self):
        from app.services.supervisor.outline_tools import _OUTLINE_CORE_TOOLS
        assert len(_OUTLINE_CORE_TOOLS) == 15

    def test_all_new_tools_are_structured_tools(self):
        from langchain_core.tools import StructuredTool
        from app.services.supervisor.outline_tools import _OUTLINE_CORE_TOOLS
        new_tool_names = {
            "generate_macro_outline", "generate_meso_outline", "generate_micro_outline",
            "generate_character_details",
            "edit_macro_outline", "edit_meso_outline", "edit_micro_outline",
            "edit_character_details",
        }
        for t in _OUTLINE_CORE_TOOLS:
            if t.name in new_tool_names:
                assert isinstance(t, StructuredTool), f"{t.name} is not a StructuredTool"


# ── Input Schemas ──


class TestInputSchemas:
    def test_generate_character_details_input_defaults(self):
        from app.services.supervisor.outline_tools import GenerateCharacterDetailsInput
        s = GenerateCharacterDetailsInput()
        assert s.idea == ""

    def test_generate_character_details_input_with_idea(self):
        from app.services.supervisor.outline_tools import GenerateCharacterDetailsInput
        s = GenerateCharacterDetailsInput(idea="让女主角更强")
        assert s.idea == "让女主角更强"

    def test_edit_character_details_input_required_suggestion(self):
        from app.services.supervisor.outline_tools import EditCharacterDetailsInput
        s = EditCharacterDetailsInput(suggestion="修改主角性格")
        assert s.suggestion == "修改主角性格"
        assert s.character_name == ""

    def test_edit_character_details_input_with_character_name(self):
        from app.services.supervisor.outline_tools import EditCharacterDetailsInput
        s = EditCharacterDetailsInput(suggestion="修改性格", character_name="李明")
        assert s.character_name == "李明"

    def test_edit_character_details_input_requires_suggestion(self):
        from app.services.supervisor.outline_tools import EditCharacterDetailsInput
        with pytest.raises(ValidationError):
            EditCharacterDetailsInput()

    def test_generate_macro_outline_input(self):
        from app.services.supervisor.outline_tools import GenerateMacroOutlineInput
        s = GenerateMacroOutlineInput(idea="修仙世界", tags=["玄幻"])
        assert s.idea == "修仙世界"
        assert s.tags == ["玄幻"]

    def test_generate_meso_outline_input(self):
        from app.services.supervisor.outline_tools import GenerateMesoOutlineInput
        s = GenerateMesoOutlineInput(idea="增加转折")
        assert s.idea == "增加转折"

    def test_generate_micro_outline_input(self):
        from app.services.supervisor.outline_tools import GenerateMicroOutlineInput
        s = GenerateMicroOutlineInput(idea="细化战斗场景")
        assert s.idea == "细化战斗场景"


# ── 辅助函数 ──


class TestExtractToolCallArgs:
    def test_extracts_matching_tool_call(self):
        from app.services.supervisor.outline_tools import _extract_tool_call_args
        msg = MagicMock()
        msg.tool_calls = [{"name": "submit_macro_outline", "args": {"story": {"title": "T"}}}]
        result = _extract_tool_call_args(msg, "submit_macro_outline")
        assert result == {"story": {"title": "T"}}

    def test_returns_none_when_no_tool_calls(self):
        from app.services.supervisor.outline_tools import _extract_tool_call_args
        msg = MagicMock()
        msg.tool_calls = []
        result = _extract_tool_call_args(msg, "submit_macro_outline")
        assert result is None

    def test_returns_none_when_wrong_tool_name(self):
        from app.services.supervisor.outline_tools import _extract_tool_call_args
        msg = MagicMock()
        msg.tool_calls = [{"name": "other_tool", "args": {}}]
        result = _extract_tool_call_args(msg, "submit_macro_outline")
        assert result is None

    def test_returns_none_when_args_not_dict(self):
        from app.services.supervisor.outline_tools import _extract_tool_call_args
        msg = MagicMock()
        msg.tool_calls = [{"name": "submit_macro_outline", "args": "not_a_dict"}]
        result = _extract_tool_call_args(msg, "submit_macro_outline")
        assert result is None

    def test_unwrap_nested_args_macro_outline(self):
        """When LLM wraps args under one extra key like 'macro_outline', _try_unwrap_nested_args auto-unwraps."""
        from app.services.supervisor.outline_tools import _try_unwrap_nested_args
        from app.services.work_service import SUBMIT_MACRO_OUTLINE_TOOL

        nested = {
            "macro_outline": {
                "story": {"title": "T"},
                "macro_phases": [{"id": "P1"}],
                "core_characters": [{"name": "A"}],
            }
        }
        result = _try_unwrap_nested_args(nested, SUBMIT_MACRO_OUTLINE_TOOL)
        assert result == nested["macro_outline"]

    def test_no_unwrap_when_already_flat(self):
        from app.services.supervisor.outline_tools import _try_unwrap_nested_args
        from app.services.work_service import SUBMIT_MACRO_OUTLINE_TOOL

        flat = {
            "story": {"title": "T"},
            "macro_phases": [{"id": "P1"}],
            "core_characters": [{"name": "A"}],
        }
        result = _try_unwrap_nested_args(flat, SUBMIT_MACRO_OUTLINE_TOOL)
        assert result is flat

    def test_no_unwrap_when_nested_value_not_dict(self):
        from app.services.supervisor.outline_tools import _try_unwrap_nested_args
        from app.services.work_service import SUBMIT_MACRO_OUTLINE_TOOL

        args = {"macro_outline": "not_a_dict"}
        result = _try_unwrap_nested_args(args, SUBMIT_MACRO_OUTLINE_TOOL)
        assert result is args

    def test_no_unwrap_when_multiple_top_level_keys(self):
        from app.services.supervisor.outline_tools import _try_unwrap_nested_args
        from app.services.work_service import SUBMIT_MACRO_OUTLINE_TOOL

        args = {
            "extra_key": {"story": {"title": "T"}},
            "story": {"title": "T"},
        }
        result = _try_unwrap_nested_args(args, SUBMIT_MACRO_OUTLINE_TOOL)
        assert result is args

    def test_unwrap_meso_outline(self):
        from app.services.supervisor.outline_tools import _try_unwrap_nested_args
        from app.services.work_service import SUBMIT_MESO_OUTLINE_TOOL

        nested = {"meso_stages_data": {"meso_doc": "这是中纲文档内容"}}
        result = _try_unwrap_nested_args(nested, SUBMIT_MESO_OUTLINE_TOOL)
        assert result == {"meso_doc": "这是中纲文档内容"}

    def test_unwrap_micro_outline(self):
        from app.services.supervisor.outline_tools import _try_unwrap_nested_args
        from app.services.work_service import SUBMIT_MICRO_OUTLINE_TOOL

        nested = {"outline": {"micro_doc": "这是小纲文档内容"}}
        result = _try_unwrap_nested_args(nested, SUBMIT_MICRO_OUTLINE_TOOL)
        assert result == {"micro_doc": "这是小纲文档内容"}

    def test_no_unwrap_when_no_overlap_with_schema(self):
        from app.services.supervisor.outline_tools import _try_unwrap_nested_args
        from app.services.work_service import SUBMIT_MACRO_OUTLINE_TOOL

        # Single key, value is dict, but no fields match schema
        args = {"random_key": {"foo": "bar", "baz": 123}}
        result = _try_unwrap_nested_args(args, SUBMIT_MACRO_OUTLINE_TOOL)
        assert result is args


# ── generate_macro_outline coroutine ──


class TestGenerateMacroOutlineCoroutine:
    @pytest.mark.asyncio
    async def test_returns_error_without_user_id(self):
        from app.services.supervisor.outline_tools import _generate_macro_outline_coroutine
        mock_db = MagicMock()
        config = {"configurable": {"user_id": None, "db": mock_db}}
        result = await _generate_macro_outline_coroutine("test idea", ["test"], config)
        parsed = json.loads(result)
        assert parsed["status"] == "error"
        assert "未认证" in parsed["message"]

    @pytest.mark.asyncio
    async def test_calls_invoke_and_persist_and_returns_success(self):
        from app.services.supervisor.outline_tools import _generate_macro_outline_coroutine
        from app.services.work_service import _OUTLINE_GENERATION_CTX

        mock_db = MagicMock()
        mock_emit = MagicMock()
        config = {
            "configurable": {
                "user_id": "u-1",
                "db": mock_db,
                "emit": mock_emit,
            },
        }

        mock_args = {
            "story": {"title": "测试作品", "genre": "玄幻"},
            "macro_phases": [{"id": "mp1", "name": "起始"}],
            "core_characters": [{"name": "主角", "role_type": "主角"}],
            "ending": {},
        }

        with patch(
            "app.services.supervisor.outline_tools._invoke_and_persist",
            new_callable=AsyncMock,
            return_value=mock_args,
        ) as mock_invoke:
            # 需要在 ctx 中设置 work_id，以便 coroutine 能读到
            result = await _generate_macro_outline_coroutine("修仙世界", ["玄幻"], config)
            parsed = json.loads(result)
            assert parsed["status"] == "applied"
            assert parsed["tool"] == "generate_macro_outline"
            mock_invoke.assert_called_once()


# ── generate_meso_outline coroutine ──


class TestGenerateMesoOutlineCoroutine:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_work_id(self):
        from app.services.supervisor.outline_tools import _generate_meso_outline_coroutine

        mock_db = MagicMock()
        config = {"configurable": {"user_id": "u-1", "db": mock_db}}
        # mock _get_work_id to raise
        with patch(
            "app.services.supervisor.outline_tools._get_work_id",
            side_effect=ValueError("no work_id"),
        ):
            result = await _generate_meso_outline_coroutine("idea", config)
            parsed = json.loads(result)
            assert parsed["status"] == "error"

    @pytest.mark.asyncio
    async def test_returns_error_when_no_macro_phases(self):
        from app.services.supervisor.outline_tools import _generate_meso_outline_coroutine

        mock_work = MagicMock()
        mock_work.outline_tree = {"outline": {"macro_phases": []}}
        mock_work.idea = "test"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {"configurable": {"user_id": "u-1", "db": mock_db}}
        with patch(
            "app.services.supervisor.outline_tools._get_work_id",
            return_value="w-1",
        ):
            result = await _generate_meso_outline_coroutine("idea", config)
            parsed = json.loads(result)
            assert parsed["status"] == "error"
            assert "Macro Outline" in parsed["message"]


# ── generate_character_details coroutine ──


class TestGenerateCharacterDetailsCoroutine:
    @pytest.mark.asyncio
    async def test_returns_error_when_no_core_characters(self):
        from app.services.supervisor.outline_tools import _generate_character_details_coroutine

        mock_work = MagicMock()
        mock_work.outline_tree = {"outline": {"macro_phases": [{"id": "mp1"}], "core_characters": []}}
        mock_work.idea = "test"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {"configurable": {"user_id": "u-1", "db": mock_db}}
        with patch(
            "app.services.supervisor.outline_tools._get_work_id",
            return_value="w-1",
        ):
            result = await _generate_character_details_coroutine("", config)
            parsed = json.loads(result)
            assert parsed["status"] == "error"
            assert "core_characters" in parsed["message"]

    @pytest.mark.asyncio
    async def test_success_with_core_characters(self):
        from app.services.supervisor.outline_tools import _generate_character_details_coroutine

        mock_work = MagicMock()
        mock_work.outline_tree = {
            "outline": {
                "macro_phases": [{"id": "mp1"}],
                "core_characters": [{"name": "主角", "role_type": "主角"}],
            },
            "story": {"title": "测试"},
        }
        mock_work.idea = "test"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {"configurable": {"user_id": "u-1", "db": mock_db}}

        mock_args = [
            {"name": "主角", "appearance": "帅气", "personality": "勇敢"},
        ]

        with patch(
            "app.services.supervisor.outline_tools._get_work_id",
            return_value="w-1",
        ), patch(
            "app.services.supervisor.outline_tools._invoke_and_persist",
            new_callable=AsyncMock,
            return_value=mock_args,
        ):
            result = await _generate_character_details_coroutine("", config)
            parsed = json.loads(result)
            assert parsed["status"] == "applied"
            assert parsed["tool"] == "generate_character_details"


# ── edit_macro_outline coroutine ──


class TestEditMacroOutlineCoroutine:
    @pytest.mark.asyncio
    async def test_returns_error_when_empty_suggestion(self):
        from app.services.supervisor.outline_tools import _edit_macro_outline_coroutine

        mock_db = MagicMock()
        config = {"configurable": {"user_id": "u-1", "db": mock_db}}
        with patch(
            "app.services.supervisor.outline_tools._get_work_id",
            return_value="w-1",
        ):
            result = await _edit_macro_outline_coroutine("", "", config)
            parsed = json.loads(result)
            assert parsed["status"] == "error"
            assert "不能为空" in parsed["message"]

    @pytest.mark.asyncio
    async def test_returns_error_when_no_macro_phases(self):
        from app.services.supervisor.outline_tools import _edit_macro_outline_coroutine

        mock_work = MagicMock()
        mock_work.outline_tree = {"outline": {"macro_phases": []}}
        mock_work.idea = "test"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {"configurable": {"user_id": "u-1", "db": mock_db}}
        with patch(
            "app.services.supervisor.outline_tools._get_work_id",
            return_value="w-1",
        ):
            result = await _edit_macro_outline_coroutine("增加一个阶段", "", config)
            parsed = json.loads(result)
            assert parsed["status"] == "error"
            assert "宏观大纲" in parsed["message"]


# ── edit_character_details coroutine ──


class TestEditCharacterDetailsCoroutine:
    @pytest.mark.asyncio
    async def test_returns_error_when_empty_suggestion(self):
        from app.services.supervisor.outline_tools import _edit_character_details_coroutine

        mock_db = MagicMock()
        config = {"configurable": {"user_id": "u-1", "db": mock_db}}
        with patch(
            "app.services.supervisor.outline_tools._get_work_id",
            return_value="w-1",
        ):
            result = await _edit_character_details_coroutine("", "", config)
            parsed = json.loads(result)
            assert parsed["status"] == "error"

    @pytest.mark.asyncio
    async def test_returns_error_when_no_characters(self):
        from app.services.supervisor.outline_tools import _edit_character_details_coroutine

        mock_work = MagicMock()
        mock_work.outline_tree = {"characters": []}
        mock_work.idea = "test"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {"configurable": {"user_id": "u-1", "db": mock_db}}
        with patch(
            "app.services.supervisor.outline_tools._get_work_id",
            return_value="w-1",
        ):
            result = await _edit_character_details_coroutine("修改性格", "", config)
            parsed = json.loads(result)
            assert parsed["status"] == "error"
            assert "角色卡" in parsed["message"]

    @pytest.mark.asyncio
    async def test_returns_error_when_character_name_not_found(self):
        from app.services.supervisor.outline_tools import _edit_character_details_coroutine

        mock_work = MagicMock()
        mock_work.outline_tree = {
            "characters": [{"name": "李明", "personality": "勇敢"}],
        }
        mock_work.idea = "test"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {"configurable": {"user_id": "u-1", "db": mock_db}}
        with patch(
            "app.services.supervisor.outline_tools._get_work_id",
            return_value="w-1",
        ):
            result = await _edit_character_details_coroutine("修改性格", "不存在的角色", config)
            parsed = json.loads(result)
            assert parsed["status"] == "error"
            assert "未找到" in parsed["message"]


# ── outline_done 事件 payload ──


class TestOutlineStageErrorEmit:
    def test_emit_outline_stage_error_payload(self):
        from app.services.supervisor.outline_tools import _emit_outline_stage_error

        emitted = []

        def capture(event, data):
            emitted.append((event, data))

        _emit_outline_stage_error(
            capture,
            work_id="w-1",
            title="尸帝",
            stage="micro",
            message="小纲生成失败：timeout",
        )

        event, data = emitted[0]
        assert event == "outline_stage_error"
        assert data["stage"] == "micro"
        assert "小纲生成失败" in data["message"]


class TestOutlineDoneEmitPayload:
    def test_emit_outline_done_includes_title_for_stage(self):
        from app.services.supervisor.outline_tools import _emit_outline_done

        emitted = []

        def capture(event, data):
            emitted.append((event, data))

        _emit_outline_done(capture, work_id="w-1", title="尸帝", stage="meso")

        assert len(emitted) == 1
        event, data = emitted[0]
        assert event == "outline_done"
        assert data == {"work_id": "w-1", "title": "尸帝", "stage": "meso"}

    def test_emit_outline_done_macro_without_stage(self):
        from app.services.supervisor.outline_tools import _emit_outline_done

        emitted = []

        def capture(event, data):
            emitted.append((event, data))

        _emit_outline_done(capture, work_id="w-1", title="尸帝")

        event, data = emitted[0]
        assert data == {"work_id": "w-1", "title": "尸帝"}


# ── Deprecated 标记 ──


class TestDeprecatedTools:
    def test_edit_outline_by_suggestion_is_deprecated(self):
        from app.services.supervisor.outline_tools import edit_outline_by_suggestion
        assert "已废弃" in edit_outline_by_suggestion.description or "废弃" in edit_outline_by_suggestion.description

    def test_generate_outline_removed_from_core_tools(self):
        from app.services.supervisor.outline_tools import _OUTLINE_CORE_TOOLS
        names = [t.name for t in _OUTLINE_CORE_TOOLS]
        assert "generate_outline" not in names
