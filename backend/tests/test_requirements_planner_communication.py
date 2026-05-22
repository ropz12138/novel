"""测试需求规划子Agent通信链路修复

验证：
1. plan() 能从 analyze_requirements 工具返回文本中提取结构化 questions
2. plan() 能从 analyze_requirements 工具返回文本中提取结构化 todolist
3. plan() 的 result 包含 intent_summary
4. _dispatch_requirements_planner_coroutine 返回值包含具体问题内容
5. 当没有 questions 时返回 todolist 摘要
6. LLM 最终回复中包含关键信息时也能正确解析
"""

import asyncio
import json
import sys

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "/root/Novel/backend")


# ── 1. plan() 结构化解析测试 ──


class TestRequirementsPlannerPlanParsing:
    """验证 RequirementsPlannerAgent.plan() 的结构化结果解析"""

    @pytest.mark.asyncio
    async def test_plan_extracts_questions_from_tool_result(self):
        """analyze_requirements 工具返回含问题的文本时，plan() 应提取结构化 questions"""
        from app.services.supervisor.requirements_planner_agent import RequirementsPlannerAgent
        from langchain_core.messages import AIMessage, ToolMessage

        agent = RequirementsPlannerAgent(emit=lambda e, d: None)

        tool_return_text = (
            "需求分析完成。发现 2 个需要澄清的问题。\n"
            "- 男主的秦始皇血脉觉醒时机是什么时候？\n"
            "- 丧尸病毒的来源是考古挖掘还是自然变异？"
        )

        # 模拟 graph.astream 返回的事件流
        async def fake_astream(*args, **kwargs):
            # 第一步：LLM 调用工具 → AIMessage with tool_calls
            yield {
                "agent": {
                    "messages": [AIMessage(
                        content="",
                        tool_calls=[{"name": "analyze_requirements", "args": {"message": "测试"}, "id": "tc1"}],
                    )],
                },
            }
            # 第二步：工具返回结果
            yield {
                "tools": {
                    "messages": [ToolMessage(content=tool_return_text, tool_call_id="tc1")],
                },
            }
            # 第三步：LLM 最终回复
            yield {
                "agent": {
                    "messages": [AIMessage(content="需求分析已完成。")],
                },
            }

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = MagicMock()
            mock_graph.astream = fake_astream
            mock_build.return_value = mock_graph

            result = await agent.plan(
                message="写一部丧尸末日小说",
                work_id=None,
                history=[],
                db=MagicMock(),
            )

        assert len(result["questions"]) == 2
        assert "秦始皇血脉觉醒时机" in result["questions"][0]
        assert "丧尸病毒" in result["questions"][1]
        assert result["ready_to_execute"] is False

    @pytest.mark.asyncio
    async def test_plan_extracts_todolist_from_tool_result(self):
        """analyze_requirements 工具返回含任务的文本时，plan() 应提取结构化 todolist"""
        from app.services.supervisor.requirements_planner_agent import RequirementsPlannerAgent
        from langchain_core.messages import AIMessage, ToolMessage

        agent = RequirementsPlannerAgent(emit=lambda e, d: None)

        tool_return_text = (
            "需求已明确，生成了 3 条任务。\n"
            "- 创建大纲（含秦始皇血脉设定）\n"
            "- 设计男主嬴XX的角色卡\n"
            "- 规划丧尸末日世界观"
        )

        async def fake_astream(*args, **kwargs):
            yield {
                "agent": {
                    "messages": [AIMessage(
                        content="",
                        tool_calls=[{"name": "analyze_requirements", "args": {"message": "测试"}, "id": "tc1"}],
                    )],
                },
            }
            yield {
                "tools": {
                    "messages": [ToolMessage(content=tool_return_text, tool_call_id="tc1")],
                },
            }
            yield {
                "agent": {
                    "messages": [AIMessage(content="需求规划已完成，信息充分。")],
                },
            }

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = MagicMock()
            mock_graph.astream = fake_astream
            mock_build.return_value = mock_graph

            result = await agent.plan(
                message="写一部丧尸末日小说",
                work_id=None,
                history=[],
                db=MagicMock(),
            )

        assert len(result["todolist"]) == 3
        assert result["ready_to_execute"] is True
        assert "大纲" in result["todolist"][0]

    @pytest.mark.asyncio
    async def test_plan_returns_intent_summary(self):
        """plan() 的 result 应包含 intent_summary"""
        from app.services.supervisor.requirements_planner_agent import RequirementsPlannerAgent
        from langchain_core.messages import AIMessage, ToolMessage

        agent = RequirementsPlannerAgent(emit=lambda e, d: None)

        tool_return_text = (
            "需求分析完成。发现 1 个需要澄清的问题。\n"
            "- 男主的异能类型是什么？"
        )

        async def fake_astream(*args, **kwargs):
            yield {
                "agent": {
                    "messages": [AIMessage(
                        content="",
                        tool_calls=[{"name": "analyze_requirements", "args": {"message": "测试"}, "id": "tc1"}],
                    )],
                },
            }
            yield {
                "tools": {
                    "messages": [ToolMessage(content=tool_return_text, tool_call_id="tc1")],
                },
            }
            yield {
                "agent": {
                    "messages": [AIMessage(
                        content="需求分析已完成，需要用户确认男主异能类型。intent_summary: 为一部丧尸末日题材的小说进行需求澄清。"
                    )],
                },
            }

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = MagicMock()
            mock_graph.astream = fake_astream
            mock_build.return_value = mock_graph

            result = await agent.plan(
                message="写一部丧尸末日小说",
                work_id=None,
                history=[],
                db=MagicMock(),
            )

        assert result["intent_summary"] != ""
        assert "丧尸末日" in result["intent_summary"]

    @pytest.mark.asyncio
    async def test_plan_emits_requirements_ready_with_correct_counts(self):
        """plan() 应正确 emit requirements_ready 事件"""
        from app.services.supervisor.requirements_planner_agent import RequirementsPlannerAgent
        from langchain_core.messages import AIMessage, ToolMessage

        emitted_events = []

        def capture_emit(event, data):
            emitted_events.append((event, data))

        agent = RequirementsPlannerAgent(emit=capture_emit)

        tool_return_text = (
            "需求分析完成。发现 2 个需要澄清的问题。\n"
            "- 问题1\n"
            "- 问题2"
        )

        async def fake_astream(*args, **kwargs):
            yield {
                "agent": {
                    "messages": [AIMessage(
                        content="",
                        tool_calls=[{"name": "analyze_requirements", "args": {"message": "测试"}, "id": "tc1"}],
                    )],
                },
            }
            yield {
                "tools": {
                    "messages": [ToolMessage(content=tool_return_text, tool_call_id="tc1")],
                },
            }
            yield {
                "agent": {
                    "messages": [AIMessage(content="需求分析完成。")],
                },
            }

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = MagicMock()
            mock_graph.astream = fake_astream
            mock_build.return_value = mock_graph

            await agent.plan(
                message="测试",
                work_id=None,
                history=[],
                db=MagicMock(),
            )

        ready_events = [(e, d) for e, d in emitted_events if e == "requirements_ready"]
        assert len(ready_events) == 1
        assert ready_events[0][1]["questions_count"] == 2


# ── 2. _dispatch_requirements_planner_coroutine 返回值测试 ──


class TestDispatchRequirementsPlannerReturn:
    """验证 dispatch_requirements_planner 返回值包含具体内容"""

    @pytest.mark.asyncio
    async def test_return_includes_question_details(self):
        """有 questions 时，返回值应包含具体问题内容"""
        from app.services.supervisor.tools import dispatch_requirements_planner

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        config = {
            "configurable": {
                "db": mock_db,
                "emit": lambda e, d: None,
                "supervisor_session_id": None,
            },
        }

        mock_result = {
            "intent_summary": "丧尸末日小说需求澄清",
            "questions": [
                "男主的秦始皇血脉觉醒时机是什么？",
                "丧尸病毒的来源是什么？",
            ],
            "todolist": [],
            "ready_to_execute": False,
        }

        with patch(
            "app.services.supervisor.requirements_planner_agent.RequirementsPlannerAgent.plan",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await dispatch_requirements_planner.coroutine(
                message="写一部丧尸末日小说",
                work_id=None,
                config=config,
            )

        assert "秦始皇血脉" in result
        assert "丧尸病毒" in result

    @pytest.mark.asyncio
    async def test_return_includes_todolist_summary_when_no_questions(self):
        """无 questions 时，返回值应包含任务清单摘要"""
        from app.services.supervisor.tools import dispatch_requirements_planner

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        config = {
            "configurable": {
                "db": mock_db,
                "emit": lambda e, d: None,
                "supervisor_session_id": None,
            },
        }

        mock_result = {
            "intent_summary": "丧尸末日小说需求规划",
            "questions": [],
            "todolist": [
                {"id": "T1", "task": "创建大纲", "owner": "outline_agent"},
                {"id": "T2", "task": "设计角色卡", "owner": "supervisor"},
            ],
            "ready_to_execute": True,
        }

        with patch(
            "app.services.supervisor.requirements_planner_agent.RequirementsPlannerAgent.plan",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await dispatch_requirements_planner.coroutine(
                message="写一部丧尸末日小说",
                work_id=None,
                config=config,
            )

        assert "2" in result
        assert "需求已明确" in result
