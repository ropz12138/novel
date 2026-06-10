"""EvaluationAgent.evaluate_chapter 不应在读取 configurable 时抛 UnboundLocalError。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_evaluate_chapter_reads_enable_child_todolist_from_base_configurable():
    from app.services.evaluation_agent import EvaluationAgent

    agent = EvaluationAgent()
    mock_db = MagicMock()
    mock_chapter = MagicMock()
    mock_chapter.title = "第一章"
    mock_db.query.return_value.filter_by.return_value.first.return_value = mock_chapter

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={"messages": []})

    with patch.object(agent, "_build_graph", return_value=mock_graph) as mock_build:
        title, editor, reader, sync = await agent.evaluate_chapter(
            db=mock_db,
            work_id="w-1",
            chapter_number=1,
            base_configurable={"enable_child_todolist": True, "emit": lambda e, d: None},
        )

    mock_build.assert_called_once_with(enable_child_todolist=True)
    assert title == "第一章"
    assert editor == reader == sync == ""
