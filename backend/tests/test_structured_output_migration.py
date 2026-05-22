"""测试所有 LLM JSON 输出环节已转为 with_structured_output

验证 5 处改动：
1. requirements_planner_tools — _analyze_requirements_coroutine
2. evaluation_tools — _evaluate_as_editor_coroutine（评分 via tool-calling，见 test_evaluation_scoring_tool_calling.py）
3. evaluation_tools — _evaluate_as_reader_coroutine（评分 via tool-calling，见 test_evaluation_scoring_tool_calling.py）
4. chapter_tools — _update_characters_after_chapter_coroutine
5. nodes.py — update_characters_node

每处验证：
- 使用 with_structured_output 而非 regex + json.loads
- 向后兼容（返回值格式不变）
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, "/root/Novel/backend")

GET_LLM_PATCH = "app.services.supervisor.sub_agent_base.get_llm"


def _make_mock_llm(return_value):
    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(return_value=return_value)
    return mock_llm


class _FakePrompt:
    def __or__(self, other):
        return other


# ── 1. 需求分析 ──
# requirements_planner_tools 中 PromptTemplate 是函数内 import，所以 patch 源模块
# Path.read_text 也是函数内调用


class TestRequirementsPlannerStructuredOutput:

    @pytest.mark.asyncio
    async def test_analyze_returns_structured_result(self):
        from app.services.supervisor.requirements_planner_tools import (
            _analyze_requirements_coroutine,
        )

        mock_result = MagicMock()
        mock_result.intent_summary = "丧尸末日小说需求规划"
        mock_result.questions = ["男主的秦始皇血脉觉醒时机？"]
        mock_result.todolist = []
        mock_result.ready_to_execute = False

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}
        mock_llm = _make_mock_llm(mock_result)

        with patch(GET_LLM_PATCH, return_value=mock_llm), \
             patch("langchain_core.prompts.PromptTemplate") as mock_pt, \
             patch.object(Path, "read_text", return_value="dummy"):
            mock_pt.from_template.return_value = _FakePrompt()
            result = await _analyze_requirements_coroutine(
                message="写一部丧尸末日小说",
                work_context="",
                history="",
                config=config,
            )

        mock_llm.with_structured_output.assert_called_once()
        assert "需要澄清" in result or "问题" in result


# ── 2/3. 章节评估打分已改为 tool-calling，见 test_evaluation_scoring_tool_calling.py ──


# ── 4. 章节工具角色更新 ──
# chapter_tools 中 PromptTemplate 是模块级 import，需 patch 模块属性


class TestChapterToolsCharacterUpdateStructuredOutput:

    @pytest.mark.asyncio
    async def test_character_update_uses_structured_output(self):
        from app.services.agent.chapter_tools import (
            _update_characters_after_chapter_coroutine,
        )

        mock_char = MagicMock()
        mock_char.name = "嬴XX"
        mock_char.role_type = "男主"
        mock_char.current_status = "存活"
        mock_char.current_goal = "生存"
        mock_char.last_location = "学校"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.all.return_value = [mock_char]

        mock_update = MagicMock()
        mock_update.name = "嬴XX"
        mock_update.current_status = "已觉醒异能"
        mock_update.current_goal = "保护女主"
        mock_update.last_location = "废弃医院"

        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}
        mock_llm_result = MagicMock()
        mock_llm_result.character_updates = [mock_update]
        mock_llm = _make_mock_llm(mock_llm_result)

        with patch(GET_LLM_PATCH, return_value=mock_llm), \
             patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt, \
             patch.object(Path, "read_text", return_value="dummy"):
            mock_pt.from_template.return_value = _FakePrompt()
            result = await _update_characters_after_chapter_coroutine(
                work_id="w-1",
                chapter_number=1,
                chapter_content="测试正文",
                config=config,
            )

        mock_llm.with_structured_output.assert_called_once()
        assert "嬴XX" in result


# ── 5. nodes.py 角色更新 ──
# nodes.py 中 PromptTemplate 是模块级 import


class TestNodesCharacterUpdateStructuredOutput:

    @pytest.mark.asyncio
    async def test_update_characters_node_uses_structured_output(self):
        from app.services.agent.nodes import update_characters_node

        mock_char = MagicMock()
        mock_char.name = "嬴XX"
        mock_char.role_type = "男主"
        mock_char.current_status = "存活"
        mock_char.current_goal = "生存"
        mock_char.last_location = "学校"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.all.return_value = [mock_char]

        mock_update = MagicMock()
        mock_update.name = "嬴XX"
        mock_update.current_status = "觉醒异能"
        mock_update.current_goal = "揭开真相"
        mock_update.last_location = "地下实验室"

        state = MagicMock()
        state.work_id = "w-1"
        state.chapter_number = 1
        state.chapter_title = "第一章"
        state.chapter_content = "测试正文"

        mock_llm_result = MagicMock()
        mock_llm_result.character_updates = [mock_update]
        mock_llm = _make_mock_llm(mock_llm_result)

        with patch("app.services.agent.nodes._get_llm", return_value=mock_llm), \
             patch("app.services.agent.nodes.PromptTemplate") as mock_pt, \
             patch("app.services.agent.nodes._read_prompt", return_value="dummy"):
            mock_pt.from_template.return_value = _FakePrompt()
            result = await update_characters_node(
                state, emit=lambda e, d: None, db=mock_db,
            )

        mock_llm.with_structured_output.assert_called_once()
        assert result is not None
