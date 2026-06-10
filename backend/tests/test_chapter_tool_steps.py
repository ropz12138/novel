"""ChapterAgent 应向前端 emit 子工具调用步骤。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage


def test_format_tool_step_label():
    from app.services.supervisor.chapter_agent import _format_tool_step_label

    assert _format_tool_step_label("generate_patch_edit", 1) == "修改第1章"
    assert _format_tool_step_label("rewrite_chapter", 3) == "重写第3章"
    assert _format_tool_step_label("read_chapter", 2) == "读取第2章"
    assert _format_tool_step_label("query_characters_by_chapter", 1) == "查询角色第1章"
    assert _format_tool_step_label("unknown_tool", 5) == "unknown_tool第5章"
    assert _format_tool_step_label("read_chapter", None) == "读取"


@pytest.mark.asyncio
async def test_chapter_agent_emits_stage_start_for_tool_calls():
    from app.services.supervisor.chapter_agent import ChapterAgent

    emitted: list[tuple[str, dict]] = []

    def emit(event, data):
        emitted.append((event, data))

    agent = ChapterAgent(emit=emit)

    ai_with_tool_calls = AIMessage(
        content="",
        tool_calls=[
            {"name": "generate_patch_edit", "args": {}, "id": "tc1"},
            {"name": "read_chapter", "args": {}, "id": "tc2"},
        ],
    )
    tool_msg_1 = ToolMessage(content="done", name="generate_patch_edit", tool_call_id="tc1")
    tool_msg_2 = ToolMessage(content="content", name="read_chapter", tool_call_id="tc2")

    mock_graph = MagicMock()

    async def mock_astream(state, config=None):
        yield {"agent": {"messages": [ai_with_tool_calls]}}
        yield {"tools": {"messages": [tool_msg_1, tool_msg_2]}}
        yield {"agent": {"messages": [AIMessage(content="完成")]}}
        yield {"messages": [ai_with_tool_calls, tool_msg_1, tool_msg_2, AIMessage(content="完成")]}

    mock_graph.astream = mock_astream
    mock_graph.compile = MagicMock(return_value=mock_graph)

    mock_db = MagicMock()
    mock_chapter = MagicMock()
    mock_chapter.content = "test"
    mock_db.query.return_value.filter_by.return_value.first.return_value = mock_chapter

    with patch.object(agent, "_build_graph", return_value=mock_graph):
        with patch("app.services.supervisor.chapter_agent.build_chapter_agent_tools", return_value=[]):
            result = await agent.run(
                work_id="w1",
                user_message="改第1章",
                db=mock_db,
                chapter_number=1,
                is_new_chapter=False,
                auto_mode=True,
                base_configurable={},
            )

    stage_starts = [(e, d) for e, d in emitted if e == "stage_start"]
    labels = [d["label"] for _, d in stage_starts]

    assert "修改第1章" in labels
    assert "读取第1章" in labels

    tool_executed = [d for e, d in emitted if e == "tool_executed"]
    assert len(tool_executed) >= 1


@pytest.mark.asyncio
async def test_chapter_agent_emits_tool_executed():
    from app.services.supervisor.chapter_agent import ChapterAgent

    emitted: list[tuple[str, dict]] = []

    def emit(event, data):
        emitted.append((event, data))

    agent = ChapterAgent(emit=emit)

    ai_msg = AIMessage(
        content="",
        tool_calls=[{"name": "rewrite_chapter", "args": {}, "id": "tc1"}],
    )
    tool_msg = ToolMessage(content="saved", name="rewrite_chapter", tool_call_id="tc1")

    mock_graph = MagicMock()

    async def mock_astream(state, config=None):
        yield {"agent": {"messages": [ai_msg]}}
        yield {"tools": {"messages": [tool_msg]}}
        yield {"agent": {"messages": [AIMessage(content="done")]}}
        yield {"messages": [ai_msg, tool_msg, AIMessage(content="done")]}

    mock_graph.astream = mock_astream
    mock_graph.compile = MagicMock(return_value=mock_graph)

    mock_db = MagicMock()
    mock_chapter = MagicMock()
    mock_chapter.content = "test"
    mock_db.query.return_value.filter_by.return_value.first.return_value = mock_chapter

    with patch.object(agent, "_build_graph", return_value=mock_graph):
        with patch("app.services.supervisor.chapter_agent.build_chapter_agent_tools", return_value=[]):
            await agent.run(
                work_id="w1",
                user_message="重写第2章",
                db=mock_db,
                chapter_number=2,
                is_new_chapter=False,
                auto_mode=True,
                base_configurable={},
            )

    tool_executed_events = [d for e, d in emitted if e == "tool_executed"]
    assert len(tool_executed_events) == 1
    assert tool_executed_events[0]["tool"] == "rewrite_chapter"
