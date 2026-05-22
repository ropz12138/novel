"""评估打分环节使用 tool-calling 提交结构化结果。"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage

sys.path.insert(0, "/root/Novel/backend")

GET_LLM_PATCH = "app.services.supervisor.sub_agent_base.get_llm"


def _make_tool_call_llm(tool_name: str, args: dict):
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="",
            tool_calls=[{"name": tool_name, "args": args, "id": "call_test_1"}],
        )
    )
    return mock_llm


class _FakePrompt:
    def format(self, **kwargs):
        return "formatted prompt"

    @classmethod
    def from_template(cls, template):
        return cls()


class TestEditorEvaluationToolCalling:

    @pytest.mark.asyncio
    async def test_editor_eval_uses_bind_tools_not_structured_output(self):
        from app.services.supervisor.evaluation_tools import _evaluate_as_editor_coroutine

        args = {
            "total_score": 45,
            "scores": {"outline_fidelity": 8},
            "strengths": ["结构完整"],
            "issues": ["对话生硬"],
            "suggestions": ["增加内心独白"],
        }
        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}
        mock_llm = _make_tool_call_llm("submit_editor_evaluation", args)

        with patch(GET_LLM_PATCH, return_value=mock_llm), \
             patch("app.services.supervisor.evaluation_tools.PromptTemplate") as mock_pt, \
             patch.object(Path, "read_text", return_value="dummy"):
            mock_pt.from_template.return_value = _FakePrompt()
            result = await _evaluate_as_editor_coroutine(
                chapter_content="测试正文",
                config=config,
            )

        mock_llm.bind_tools.assert_called_once()
        bind_call_args = mock_llm.bind_tools.call_args
        assert bind_call_args[1].get("tool_choice") is None, (
            "tool_choice 不应传入，thinking mode 模型不支持"
        )
        mock_llm.with_structured_output.assert_not_called()
        assert "45" in result
        assert "对话生硬" in result

    @pytest.mark.asyncio
    async def test_editor_eval_fails_without_tool_call(self):
        from app.services.supervisor.evaluation_tools import _evaluate_as_editor_coroutine

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="未调用工具"))

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}

        with patch(GET_LLM_PATCH, return_value=mock_llm), \
             patch("app.services.supervisor.evaluation_tools.PromptTemplate") as mock_pt, \
             patch.object(Path, "read_text", return_value="dummy"):
            mock_pt.from_template.return_value = _FakePrompt()
            result = await _evaluate_as_editor_coroutine(
                chapter_content="测试正文",
                config=config,
            )

        assert "未正确调用 submit_editor_evaluation" in result


class TestReaderEvaluationToolCalling:

    @pytest.mark.asyncio
    async def test_reader_eval_uses_bind_tools(self):
        from app.services.supervisor.evaluation_tools import _evaluate_as_reader_coroutine

        args = {
            "total_score": 38,
            "scores": {"hook": 7},
            "strengths": ["代入感强"],
            "issues": ["悬念不足"],
            "suggestions": ["增加章末钩子"],
        }
        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}
        mock_llm = _make_tool_call_llm("submit_reader_evaluation", args)

        with patch(GET_LLM_PATCH, return_value=mock_llm), \
             patch("app.services.supervisor.evaluation_tools.PromptTemplate") as mock_pt, \
             patch.object(Path, "read_text", return_value="dummy"):
            mock_pt.from_template.return_value = _FakePrompt()
            result = await _evaluate_as_reader_coroutine(
                chapter_content="测试正文",
                config=config,
            )

        mock_llm.bind_tools.assert_called_once()
        assert "38" in result


class TestEvaluationAgentCollectsToolMessages:

    @pytest.mark.asyncio
    async def test_evaluate_chapter_reads_full_message_history(self):
        from app.services.evaluation_agent import EvaluationAgent

        editor_msg = ToolMessage(
            content="编辑视角评分：42/60。问题：节奏偏慢。建议：收紧中段。",
            name="evaluate_as_editor",
            tool_call_id="e1",
        )
        reader_msg = ToolMessage(
            content="读者视角评分：50/60。问题：悬念不足。建议：加强章末钩子。",
            name="evaluate_as_reader",
            tool_call_id="r1",
        )
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={"messages": [editor_msg, reader_msg]}
        )

        db = MagicMock()
        chapter = MagicMock()
        chapter.title = "第一章"
        db.query.return_value.filter_by.return_value.first.return_value = chapter

        agent = EvaluationAgent()
        with patch.object(agent, "_build_graph", return_value=mock_graph):
            title, editor, reader = await agent.evaluate_chapter(
                db=db,
                work_id="work-1",
                chapter_number=1,
            )

        assert title == "第一章"
        assert editor["total_score"] == 42
        assert "节奏偏慢" in editor["issues"]
        assert reader["total_score"] == 50


class TestWorkIdInjectedIntoPrompt:

    def test_system_prompt_contains_work_id(self):
        from app.services.evaluation_agent import _build_evaluation_system_prompt

        prompt = _build_evaluation_system_prompt(
            work_id="abc-123",
            chapter_number=3,
        )
        assert "abc-123" in prompt
        assert "第3章" in prompt
        assert "禁止猜测" in prompt

    def test_system_prompt_rejects_placeholder_default(self):
        from app.services.evaluation_agent import _build_evaluation_system_prompt

        prompt = _build_evaluation_system_prompt(
            work_id="real-uuid-here",
            chapter_number=1,
        )
        assert "default" not in prompt.split("作品ID")[1].split("\n")[0]


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
