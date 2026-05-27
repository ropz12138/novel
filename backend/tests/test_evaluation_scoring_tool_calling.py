"""评估工具纯文本输出测试

评估工具已从 tool-calling（submit_* 工具）改为纯文本 LLM 输出。
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage

sys.path.insert(0, "/root/Novel/backend")

GET_LLM_PATCH = "app.services.supervisor.sub_agent_base.get_llm"


class _FakePrompt:
    def format(self, **kwargs):
        return "formatted prompt"

    @classmethod
    def from_template(cls, template):
        return cls()


class TestEditorEvaluationFreeText:

    @pytest.mark.asyncio
    async def test_editor_eval_returns_free_text(self):
        from app.services.supervisor.evaluation_tools import _evaluate_as_editor_coroutine

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="本章结构完整，节奏流畅。建议加强对话描写。")
        )

        with patch(GET_LLM_PATCH, return_value=mock_llm), \
             patch("app.services.supervisor.evaluation_tools.PromptTemplate") as mock_pt, \
             patch.object(Path, "read_text", return_value="dummy"):
            mock_pt.from_template.return_value = _FakePrompt()
            result = await _evaluate_as_editor_coroutine(
                chapter_content="测试正文",
                config=config,
            )

        assert isinstance(result, str)
        assert "结构完整" in result
        mock_llm.bind_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_editor_eval_no_tool_call_needed(self):
        from app.services.supervisor.evaluation_tools import _evaluate_as_editor_coroutine

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="纯文本评估结果"))

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}

        with patch(GET_LLM_PATCH, return_value=mock_llm), \
             patch("app.services.supervisor.evaluation_tools.PromptTemplate") as mock_pt, \
             patch.object(Path, "read_text", return_value="dummy"):
            mock_pt.from_template.return_value = _FakePrompt()
            result = await _evaluate_as_editor_coroutine(
                chapter_content="测试正文",
                config=config,
            )

        assert result == "纯文本评估结果"


class TestReaderEvaluationFreeText:

    @pytest.mark.asyncio
    async def test_reader_eval_returns_free_text(self):
        from app.services.supervisor.evaluation_tools import _evaluate_as_reader_coroutine

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="代入感强，悬念设置合理，追更意愿高。")
        )

        with patch(GET_LLM_PATCH, return_value=mock_llm), \
             patch("app.services.supervisor.evaluation_tools.PromptTemplate") as mock_pt, \
             patch.object(Path, "read_text", return_value="dummy"):
            mock_pt.from_template.return_value = _FakePrompt()
            result = await _evaluate_as_reader_coroutine(
                chapter_content="测试正文",
                config=config,
            )

        assert isinstance(result, str)
        assert "代入感" in result
        mock_llm.bind_tools.assert_not_called()


class TestEvaluationAgentCollectsTextResults:

    @pytest.mark.asyncio
    async def test_evaluate_chapter_returns_text_tuple(self):
        from app.services.evaluation_agent import EvaluationAgent

        editor_msg = ToolMessage(
            content="编辑视角：结构完整，节奏流畅。",
            name="evaluate_as_editor",
            tool_call_id="e1",
        )
        reader_msg = ToolMessage(
            content="读者视角：代入感强，可读性好。",
            name="evaluate_as_reader",
            tool_call_id="r1",
        )
        sync_msg = ToolMessage(
            content="同步性：大纲与正文基本一致。",
            name="evaluate_chapter_outline_sync",
            tool_call_id="s1",
        )
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={"messages": [editor_msg, reader_msg, sync_msg]}
        )

        db = MagicMock()
        chapter = MagicMock()
        chapter.title = "第一章"
        db.query.return_value.filter_by.return_value.first.return_value = chapter

        agent = EvaluationAgent()
        with patch.object(agent, "_build_graph", return_value=mock_graph):
            title, editor_text, reader_text, sync_text = await agent.evaluate_chapter(
                db=db,
                work_id="work-1",
                chapter_number=1,
            )

        assert title == "第一章"
        assert isinstance(editor_text, str)
        assert "结构完整" in editor_text
        assert isinstance(reader_text, str)
        assert "代入感" in reader_text
        assert isinstance(sync_text, str)
        assert "同步性" in sync_text


class TestWorkIdInjectedIntoPrompt:

    def test_system_prompt_contains_work_id(self):
        from app.services.evaluation_agent import _build_evaluation_system_prompt

        prompt = _build_evaluation_system_prompt(
            work_id="abc-123",
            chapter_number=3,
            user_message="评估第3章",
        )
        assert "第3章" in prompt
        assert "评估第3章" in prompt
        assert "显式传入 chapter_number" in prompt

    def test_system_prompt_without_fixed_chapter(self):
        from app.services.evaluation_agent import _build_evaluation_system_prompt

        prompt = _build_evaluation_system_prompt(
            work_id="real-uuid-here",
            chapter_number=None,
            user_message="评估第9章，参考第8章结尾",
        )
        assert "未由系统固定" in prompt
        assert "第8章" in prompt


class TestEditChapterDiffFromDB:

    def test_build_diff_and_summarize(self):
        from app.services.supervisor.edit_chapter_agent import _build_diff, _summarize_diff

        old = "第一行\n第二行\n第三行\n"
        new = "第一行\n修改行\n第三行\n新增行\n"
        diff = _build_diff(old, new)
        summary = _summarize_diff(diff)
        assert summary["lines_added"] >= 1
        assert summary["lines_removed"] >= 1
        assert summary["total_changes"] == summary["lines_added"] + summary["lines_removed"]
