"""测试评估工具纯文本输出 + 子 agent 记忆机制

验证：
1. evaluate_as_editor / evaluate_as_reader 不再使用 submit 工具，直接返回纯文本
2. EVALUATION_TOOLS 中不包含 submit_* 工具
3. dispatch_evaluation 能处理纯文本评估结果
4. supervisor 配置中包含 sub_agent_memories
5. 各 dispatch 函数在子 agent 完成后将结果存入记忆
6. 各 dispatch 函数在后续调用时将历史传递给子 agent
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, "/root/Novel/backend")


# ── 1. 评估工具不再使用 submit ──


class TestEvaluationToolsFreeText:
    """验证评估工具返回纯文本，不依赖 submit 工具"""

    def test_eval_tools_no_submit_tools(self):
        """EVALUATION_TOOLS 不应包含 submit_editor_evaluation 或 submit_reader_evaluation"""
        from app.services.supervisor.evaluation_tools import EVALUATION_TOOLS

        tool_names = [t.name for t in EVALUATION_TOOLS]
        assert "submit_editor_evaluation" not in tool_names
        assert "submit_reader_evaluation" not in tool_names

    def test_eval_tools_still_has_core_tools(self):
        """EVALUATION_TOOLS 应保留核心评估工具"""
        from app.services.supervisor.evaluation_tools import EVALUATION_TOOLS

        tool_names = [t.name for t in EVALUATION_TOOLS]
        assert "evaluate_as_editor" in tool_names
        assert "evaluate_as_reader" in tool_names
        assert "evaluate_chapter_outline_sync" in tool_names

    @pytest.mark.asyncio
    async def test_evaluate_as_editor_returns_free_text(self):
        """evaluate_as_editor 应返回纯文本评估，不使用 submit 工具"""
        from app.services.supervisor.evaluation_tools import _evaluate_as_editor_coroutine

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=AIMessage(
                content="本章结构完整，情节连贯，人物性格鲜明。主要优点是...建议改进..."
            )
        )

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}

        with patch("app.services.supervisor.sub_agent_base.get_llm", return_value=mock_llm):
            result = await _evaluate_as_editor_coroutine(
                chapter_content="测试正文",
                config=config,
            )

        assert isinstance(result, str)
        assert "结构完整" in result
        mock_llm.bind_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_evaluate_as_reader_returns_free_text(self):
        """evaluate_as_reader 应返回纯文本评估"""
        from app.services.supervisor.evaluation_tools import _evaluate_as_reader_coroutine

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="读者视角：代入感强，悬念设置合理...")
        )

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}

        with patch("app.services.supervisor.sub_agent_base.get_llm", return_value=mock_llm):
            result = await _evaluate_as_reader_coroutine(
                chapter_content="测试正文",
                config=config,
            )

        assert isinstance(result, str)
        assert "代入感" in result
        mock_llm.bind_tools.assert_not_called()


# ── 2. dispatch_evaluation 处理纯文本 ──


class TestDispatchEvaluationFreeText:
    """验证 dispatch_evaluation 能处理纯文本评估结果"""

    @pytest.mark.asyncio
    async def test_dispatch_evaluation_handles_text_results(self):
        """dispatch_evaluation 应接受纯文本评估结果并正确格式化"""
        from app.services.supervisor.tools import _dispatch_evaluation_coroutine

        mock_agent = MagicMock()
        mock_agent.evaluate_chapter = AsyncMock(return_value=(
            "第一章",
            "编辑视角评估：结构完整，情节连贯。",
            "读者视角评估：代入感强，可读性好。",
            "同步性评估：大纲与正文基本一致。",
        ))

        mock_db = MagicMock()
        config = {
            "configurable": {
                "db": mock_db,
                "emit": lambda e, d: None,
                "work_id": "w1",
                "sub_agent_memories": {},
            },
        }

        with patch("app.services.evaluation_agent.EvaluationAgent", return_value=mock_agent):
            result = await _dispatch_evaluation_coroutine(
                work_id="w1",
                chapter_number=1,
                config=config,
            )

        assert isinstance(result, str)
        assert "第一章" in result
        assert "编辑视角" in result


# ── 3. 子 agent 记忆机制 ──


class TestSubAgentMemory:
    """验证子 agent 记忆机制"""

    def test_supervisor_config_initializes_sub_agent_memories(self):
        """supervisor _run_graph 应在 config 中初始化 sub_agent_memories"""
        import inspect
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        source = inspect.getsource(SupervisorAgent._run_graph)
        assert "sub_agent_memories" in source

    @pytest.mark.asyncio
    async def test_dispatch_stores_result_in_memory(self):
        """dispatch 函数完成时应将结果存入 sub_agent_memories"""
        from app.services.supervisor.tools import _dispatch_evaluation_coroutine

        mock_agent = MagicMock()
        mock_agent.evaluate_chapter = AsyncMock(return_value=(
            "第一章",
            "编辑评估文本",
            "读者评估文本",
            "同步性文本",
        ))

        memories = {}
        mock_db = MagicMock()
        config = {
            "configurable": {
                "db": mock_db,
                "emit": lambda e, d: None,
                "work_id": "w1",
                "sub_agent_memories": memories,
            },
        }

        with patch("app.services.evaluation_agent.EvaluationAgent", return_value=mock_agent):
            await _dispatch_evaluation_coroutine(
                work_id="w1",
                chapter_number=1,
                config=config,
            )

        assert "evaluation" in memories
        assert len(memories["evaluation"]) >= 1

    @pytest.mark.asyncio
    async def test_dispatch_passes_memory_to_sub_agent(self):
        """第二次 dispatch 时应将历史传递给子 agent"""
        from app.services.supervisor.tools import _dispatch_evaluation_coroutine

        captured_history = None

        mock_agent = MagicMock()

        async def mock_evaluate(**kwargs):
            nonlocal captured_history
            if "history" in kwargs:
                captured_history = kwargs["history"]
            return ("第一章", "编辑", "读者", "同步")

        mock_agent.evaluate_chapter = mock_evaluate

        memories = {"evaluation": ["之前的评估结果"]}
        mock_db = MagicMock()
        config = {
            "configurable": {
                "db": mock_db,
                "emit": lambda e, d: None,
                "work_id": "w1",
                "sub_agent_memories": memories,
            },
        }

        with patch("app.services.evaluation_agent.EvaluationAgent", return_value=mock_agent):
            await _dispatch_evaluation_coroutine(
                work_id="w1",
                chapter_number=1,
                config=config,
            )

        assert captured_history is not None
        assert "之前的评估结果" in captured_history
