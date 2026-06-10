"""generate_chapter_content / dispatch_chapter 应向调用方返回字数信息。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_llm_chain_mock(output: str):
    class _Chunk:
        def __init__(self, text: str):
            self.content = text

    mock_chain = MagicMock()

    async def _astream(_inputs):
        yield _Chunk(output)

    mock_chain.astream = _astream
    mock_prompt = MagicMock()
    mock_prompt.__or__ = MagicMock(return_value=mock_chain)
    return mock_prompt


def _make_db_for_new_chapter():
    mock_db = MagicMock()
    mock_work = MagicMock()
    mock_work.id = "w-1"
    mock_work.outline_tree = {"nodes": []}

    mock_chapter = MagicMock()
    mock_chapter.chapter_number = 1
    mock_chapter.title = "第一章"
    mock_chapter.content = "正文一二三四五"
    mock_chapter.status = "已保存"

    chapter_q = MagicMock()
    chapter_q.filter_by.return_value.first.side_effect = [
        None,
        None,
        None,
        mock_chapter,
    ]
    chapter_q.filter_by.return_value.order_by.return_value.first.return_value = None

    work_q = MagicMock()
    work_q.filter_by.return_value.first.return_value = mock_work

    metadata_q = MagicMock()
    metadata_q.filter_by.return_value.first.return_value = None

    def query_side_effect(model):
        name = getattr(model, "__name__", "")
        if name == "Chapter":
            return chapter_q
        if name == "Work":
            return work_q
        if name == "ChapterMetadata":
            return metadata_q
        return MagicMock()

    mock_db.query.side_effect = query_side_effect
    mock_db.refresh.side_effect = lambda ch: None
    return mock_db


@pytest.mark.asyncio
async def test_generate_chapter_content_return_includes_word_count():
    from app.services.agent.chapter_tools import (
        _extract_body_and_title,
        _generate_chapter_content_coroutine,
        _word_count,
    )

    mock_db = _make_db_for_new_chapter()
    config = {"configurable": {"db": mock_db, "work_id": "w-1", "emit": lambda e, d: None}}
    llm_output = "正文一二三四五\n\n标题：测试章"
    body, _ = _extract_body_and_title(llm_output, 1)
    expected_wc = _word_count(body)

    with patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt, \
         patch("app.services.supervisor.sub_agent_base.get_llm") as mock_get_llm, \
         patch(
             "app.services.chapter_outline_sync_service.ChapterOutlineSyncService.generate_and_persist",
             new_callable=AsyncMock,
         ) as mock_sync:
        mock_pt.from_template.return_value = _make_llm_chain_mock(llm_output)
        mock_get_llm.return_value = MagicMock()
        mock_sync.return_value = MagicMock(
            summary="摘要",
            key_plot_points=[],
            outline_links=[],
            involved_characters=[],
            facts=[],
            updated_at=None,
        )

        result = await _generate_chapter_content_coroutine(
            chapter_number=1,
            chapter_brief="写第一章：主角出场",
            config=config,
        )

    assert f"字数：{expected_wc} 字" in result
    assert "【系统说明】" in result


@pytest.mark.asyncio
async def test_dispatch_chapter_write_includes_word_count_in_json_result():
    from app.services.supervisor.tools import dispatch_chapter

    mock_db = MagicMock()
    mock_chapter = MagicMock()
    mock_chapter.content = "新章正文六字"
    mock_chapter.chapter_number = 1

    chapter_q = MagicMock()
    chapter_q.filter_by.return_value.first.side_effect = [
        None,  # 判断是否已有正文
        mock_chapter,  # 写作完成后读取章节
        mock_chapter,  # 元数据查询前再次读取
    ]
    chapter_q.filter_by.return_value.order_by.return_value.first.return_value = None

    mock_work = MagicMock()
    mock_work.id = "w-1"
    work_q = MagicMock()
    work_q.filter_by.return_value.first.return_value = mock_work

    metadata_q = MagicMock()
    metadata_q.filter_by.return_value.first.return_value = MagicMock()

    def query_side_effect(model):
        name = getattr(model, "__name__", "")
        if name == "Chapter":
            return chapter_q
        if name == "Work":
            return work_q
        if name == "ChapterMetadata":
            return metadata_q
        return MagicMock()

    mock_db.query.side_effect = query_side_effect

    config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}

    with patch(
        "app.services.supervisor.chapter_agent.ChapterAgent.run",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = {"message": "完成"}
        result = await dispatch_chapter.coroutine(
            instruction="写第一章",
            work_id="w-1",
            chapter_number=1,
            config=config,
        )

    data = json.loads(result)
    assert data["ok"] is True
    assert data["payload"]["word_count"] == 6
    assert "字数：6 字" in data["message"]


@pytest.mark.asyncio
async def test_dispatch_chapter_edit_auto_mode_includes_word_count():
    from app.services.supervisor.tools import dispatch_chapter

    mock_db = MagicMock()
    mock_chapter = MagicMock()
    mock_chapter.content = "编辑后共七字内容"
    mock_chapter.chapter_number = 2
    mock_chapter.title = "第二章"

    def query_side_effect(model):
        q = MagicMock()
        if getattr(model, "__name__", "") == "Chapter":
            q.filter_by.return_value.first.return_value = mock_chapter
        return q

    mock_db.query.side_effect = query_side_effect
    config = {
        "configurable": {
            "db": mock_db,
            "emit": lambda e, d: None,
            "auto_mode": True,
        },
    }

    with patch(
        "app.services.supervisor.chapter_agent.ChapterAgent.run",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = {
            "summary": {"lines_added": 1, "lines_removed": 0},
            "old_content": "旧",
            "new_content": "编辑后共七字内容",
        }
        result = await dispatch_chapter.coroutine(
            instruction="润色第二章",
            work_id="w-1",
            chapter_number=2,
            config=config,
        )

    data = json.loads(result)
    assert data["payload"]["word_count"] == 8
    assert "字数：8 字" in data["message"]
