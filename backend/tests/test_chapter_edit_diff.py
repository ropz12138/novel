"""章节编辑 diff 统计：编辑前后快照与消息累积。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage


class TestCollectMessagesFromGraphEvent:

    def test_agent_node_appends_messages(self):
        from app.services.supervisor.chapter_agent import _collect_messages_from_graph_event

        existing = [AIMessage(content="hi")]
        msg = AIMessage(content="call tool", tool_calls=[])
        updated = _collect_messages_from_graph_event(existing, "agent", {"messages": [msg]})
        assert len(updated) == 2
        assert updated[-1] is msg

    def test_tools_node_appends_tool_messages(self):
        from app.services.supervisor.chapter_agent import _collect_messages_from_graph_event

        tool_msg = ToolMessage(content="ok", name="read_chapter", tool_call_id="1")
        updated = _collect_messages_from_graph_event([], "tools", {"messages": [tool_msg]})
        assert updated == [tool_msg]

    def test_values_stream_replaces_messages_list(self):
        from app.services.supervisor.chapter_agent import _collect_messages_from_graph_event

        first = ToolMessage(content="old", name="read_chapter", tool_call_id="1")
        second = ToolMessage(content="new", name="generate_patch_edit", tool_call_id="2")
        updated = _collect_messages_from_graph_event([first], "messages", [first, second])
        assert updated == [first, second]


class TestResolveOldContentForDiff:

    def test_prefers_pre_edit_snapshot(self):
        from app.services.supervisor.chapter_agent import _resolve_old_content_for_diff

        read_msg = ToolMessage(
            content="--- 正文开始 ---\nfrom read\n--- 正文结束 ---",
            name="read_chapter",
            tool_call_id="1",
        )
        old = _resolve_old_content_for_diff(
            final_messages=[read_msg],
            pre_edit_content="snapshot content",
        )
        assert old == "snapshot content"

    def test_falls_back_to_read_chapter_tool_message(self):
        from app.services.supervisor.chapter_agent import _resolve_old_content_for_diff

        read_msg = ToolMessage(
            content="--- 正文开始 ---\nfrom read\n--- 正文结束 ---",
            name="read_chapter",
            tool_call_id="1",
        )
        old = _resolve_old_content_for_diff(final_messages=[read_msg], pre_edit_content="")
        assert old == "from read"


class TestBuildChapterEditDiffResult:

    def test_builds_summary_when_contents_differ(self):
        from app.services.supervisor.chapter_agent import build_chapter_edit_diff_result

        old = "第一行\n第二行\n第三行\n"
        new = "第一行\n改后行\n第三行\n新行\n"
        result = build_chapter_edit_diff_result(old, new)
        assert result["summary"]["lines_added"] >= 1
        assert result["summary"]["lines_removed"] >= 1
        assert result["old_content"] == old
        assert result["new_content"] == new
        assert result["diff"]


@pytest.mark.asyncio
async def test_dispatch_chapter_edit_auto_mode_diff_from_pre_edit_snapshot():
    """Agent 未返回 summary 时，dispatch 应使用编辑前 DB 快照计算 diff。"""
    from app.services.supervisor.tools import dispatch_chapter

    old_text = "第一行\n第二行\n第三行\n"
    new_text = "第一行\n改后行\n第三行\n新行\n"

    mock_db = MagicMock()
    mock_chapter = MagicMock()
    mock_chapter.content = old_text
    mock_chapter.chapter_number = 1
    mock_chapter.title = "第1章"

    emitted: list[tuple[str, dict]] = []

    def emit(event, data):
        emitted.append((event, data))

    def query_side_effect(model):
        q = MagicMock()
        if getattr(model, "__name__", "") == "Chapter":
            q.filter_by.return_value.first.return_value = mock_chapter
        return q

    mock_db.query.side_effect = query_side_effect
    config = {
        "configurable": {
            "db": mock_db,
            "emit": emit,
            "auto_mode": True,
        },
    }

    async def _run_side_effect(**_kwargs):
        mock_chapter.content = new_text
        return {"message": "修改完成"}

    with patch(
        "app.services.supervisor.chapter_agent.ChapterAgent.run",
        new_callable=AsyncMock,
        side_effect=_run_side_effect,
    ):
        result = await dispatch_chapter.coroutine(
            instruction="增加网络沟通情节",
            work_id="w-1",
            chapter_number=1,
            config=config,
        )

    data = json.loads(result)
    summary = data["payload"]["summary"]
    assert summary["lines_added"] >= 1
    assert summary["lines_removed"] >= 1
    assert "+0行" not in data["message"]

    auto_applied = [item for item in emitted if item[0] == "edit_chapter_auto_applied"]
    assert len(auto_applied) == 1
    assert auto_applied[0][1]["summary"]["lines_added"] >= 1
    assert auto_applied[0][1]["diff"]


@pytest.mark.asyncio
async def test_dispatch_chapter_auto_mode_skips_edit_chapter_diff_event():
    """自动模式不应再发出需确认的 edit_chapter_diff 事件。"""
    from app.services.supervisor.tools import dispatch_chapter

    old_text = "第一行\n第二行\n"
    new_text = "第一行\n改后\n"

    mock_db = MagicMock()
    mock_chapter = MagicMock()
    mock_chapter.content = old_text
    mock_chapter.chapter_number = 1
    mock_chapter.title = "第1章"

    emitted: list[tuple[str, dict]] = []

    def emit(event, data):
        emitted.append((event, data))

    def query_side_effect(model):
        q = MagicMock()
        if getattr(model, "__name__", "") == "Chapter":
            q.filter_by.return_value.first.return_value = mock_chapter
        return q

    mock_db.query.side_effect = query_side_effect
    config = {
        "configurable": {
            "db": mock_db,
            "emit": emit,
            "auto_mode": True,
        },
    }

    async def _run_side_effect(**kwargs):
        mock_chapter.content = new_text
        assert kwargs.get("emit_diff_event") is False
        return {"message": "done"}

    with patch(
        "app.services.supervisor.chapter_agent.ChapterAgent.run",
        new_callable=AsyncMock,
        side_effect=_run_side_effect,
    ):
        await dispatch_chapter.coroutine(
            instruction="润色",
            work_id="w-1",
            chapter_number=1,
            config=config,
        )

    event_names = [name for name, _ in emitted]
    assert "edit_chapter_auto_applied" in event_names
    assert "edit_chapter_diff" not in event_names
