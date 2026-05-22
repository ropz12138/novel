"""测试 _run_graph 的 stop_after_tool 行为

验证：
1. 当 tools 节点触发 waiting 状态后，agent 应再跑一轮生成最终回复再退出
2. 不应在 tools 节点后直接 break，导致用户看到"没下文"
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage


class TestRunGraphStopAfterTool:
    """验证 _run_graph 在 waiting 状态下的退出行为"""

    @pytest.mark.asyncio
    async def test_agent_generates_final_reply_before_stop(self):
        """tools 设置 waiting 后，agent 应再跑一轮生成最终回复再退出

        复现场景：dispatch_requirements_planner 返回后 session 进入 waiting，
        _run_graph 应继续让 agent 生成最终说明文字后再 break。
        """
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        mock_db = MagicMock()
        mock_emit = MagicMock()
        agent = SupervisorAgent(emit=mock_emit, db=mock_db, work_id=None)

        mock_session = MagicMock()
        mock_session.id = "test-session"
        mock_session.auto_mode = True
        mock_session.work_id = None
        mock_session.status = "running"
        mock_session.stage = "running"
        mock_session.active_child = None

        # 记录 emit 事件
        emitted_events = []

        def capture_emit(event, data):
            emitted_events.append(event)

        agent.emit = capture_emit

        # 模拟 LangGraph 事件流：
        # event 1: agent 调用 dispatch_requirements_planner tool
        # event 2: tools 执行，设置 waiting 状态
        # event 3: agent 生成最终回复（修复后应该出现这一步）
        agent_event_1 = {
            "agent": {
                "messages": [AIMessage(content="", tool_calls=[{"name": "dispatch_requirements_planner", "args": {}, "id": "tc1"}])],
                "current_tool": "dispatch_requirements_planner",
            }
        }

        tool_event = {
            "tools": {
                "messages": [ToolMessage(content="需求澄清完成：请先回答上述问题。", tool_call_id="tc1", name="dispatch_requirements_planner")],
            }
        }

        agent_final_event = {
            "agent": {
                "messages": [AIMessage(content="我已为你梳理了需求，请回答上述问题后再继续。")],
                "current_tool": "",
            }
        }

        # 关键：tools 执行后设置 waiting 状态
        # 我们需要 session 在 tools 节点处理后变为 waiting
        real_session_status = ["running"]

        def set_waiting():
            real_session_status[0] = "waiting"
            mock_session.status = "waiting"
            mock_session.active_child = {"type": "requirements_planner"}

        async def mock_astream(*args, **kwargs):
            yield agent_event_1
            # tools 节点执行后设置 waiting
            set_waiting()
            yield tool_event
            # 修复后，agent 应继续执行这一轮
            yield agent_final_event

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = AsyncMock()
            mock_graph.astream = mock_astream
            mock_build.return_value = mock_graph

            with patch("app.services.supervisor.supervisor_agent.message_service") as mock_msg:
                mock_msg.get_messages_by_session.return_value = []
                mock_msg.get_next_sort_order.return_value = 0
                mock_msg.create_message.return_value = None

                result = await agent._run_graph(mock_session, "帮我写一个末日科幻故事")

        # 验证：应该生成了最终回复，而不是在 tools 后就退出
        assert result.get("message") != "", (
            "agent 应在 tools 设置 waiting 后再跑一轮生成最终回复"
        )

        # 验证：supervisor_done 事件应包含最终回复
        assert "supervisor_done" in emitted_events

    @pytest.mark.asyncio
    async def test_edit_chapter_waiting_still_stops_after_agent(self):
        """章节编辑 waiting 后，agent 也应再跑一轮生成最终回复"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        mock_db = MagicMock()
        emitted_events = []

        def capture_emit(event, data):
            emitted_events.append(event)

        agent = SupervisorAgent(emit=capture_emit, db=mock_db, work_id="w1")

        mock_session = MagicMock()
        mock_session.id = "test-session"
        mock_session.auto_mode = False
        mock_session.work_id = "w1"
        mock_session.status = "running"
        mock_session.stage = "running"
        mock_session.active_child = None

        agent_event_1 = {
            "agent": {
                "messages": [AIMessage(content="", tool_calls=[{"name": "dispatch_chapter", "args": {}, "id": "tc1"}])],
                "current_tool": "dispatch_chapter",
            }
        }

        tool_event = {
            "tools": {
                "messages": [ToolMessage(content="第2章修改已完成。请等待用户确认。", tool_call_id="tc1", name="dispatch_chapter")],
            }
        }

        agent_final_event = {
            "agent": {
                "messages": [AIMessage(content="第2章修改已完成，请确认是否接受修改。")],
                "current_tool": "",
            }
        }

        def set_waiting():
            mock_session.status = "waiting"
            mock_session.active_child = {"type": "edit_chapter"}

        async def mock_astream(*args, **kwargs):
            yield agent_event_1
            set_waiting()
            yield tool_event
            yield agent_final_event

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = AsyncMock()
            mock_graph.astream = mock_astream
            mock_build.return_value = mock_graph

            with patch("app.services.supervisor.supervisor_agent.message_service") as mock_msg:
                mock_msg.get_messages_by_session.return_value = []
                mock_msg.get_next_sort_order.return_value = 0
                mock_msg.create_message.return_value = None

                result = await agent._run_graph(mock_session, "修改第二章")

        assert result.get("message") != ""
        assert "supervisor_done" in emitted_events
