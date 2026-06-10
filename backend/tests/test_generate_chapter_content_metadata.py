"""generate_chapter_content 元数据同步容错（阶段 3）"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_llm_chain_mock(output: str):
    """Mock prompt | llm 链的 astream，逐块输出正文。"""

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


def _make_db_for_new_chapter(*, metadata_sync_raises: bool):
    mock_db = MagicMock()
    mock_work = MagicMock()
    mock_work.id = "w-1"
    mock_work.outline_tree = {"nodes": []}

    mock_chapter = MagicMock()
    mock_chapter.chapter_number = 1
    mock_chapter.title = "第一章"
    mock_chapter.content = "正文内容"
    mock_chapter.status = "已保存"

    chapter_q = MagicMock()
    # 顺序校验：目标章不存在；max 章为空
    chapter_q.filter_by.return_value.first.side_effect = [
        None,  # existing_chapter
        None,  # max_chapter
        None,  # save: existing row
        mock_chapter,  # save: after add/flush 用 refresh 前的对象
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
    return mock_db, mock_chapter, metadata_sync_raises


@pytest.mark.asyncio
async def test_metadata_sync_failure_returns_warning_after_body_saved():
    from app.services.agent.chapter_tools import _generate_chapter_content_coroutine

    mock_db, _, _ = _make_db_for_new_chapter(metadata_sync_raises=True)
    config = {"configurable": {"db": mock_db, "work_id": "w-1", "emit": lambda e, d: None}}

    llm_output = "第一章\n\n正文内容。"

    with patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt, \
         patch("app.services.supervisor.sub_agent_base.get_llm") as mock_get_llm, \
         patch(
             "app.services.chapter_outline_sync_service.ChapterOutlineSyncService.generate_and_persist",
             new_callable=AsyncMock,
         ) as mock_sync:
        mock_pt.from_template.return_value = _make_llm_chain_mock(llm_output)
        mock_get_llm.return_value = MagicMock()
        mock_sync.side_effect = RuntimeError("metadata sync failed")

        result = await _generate_chapter_content_coroutine(
            chapter_number=1,
            chapter_brief="写第一章：主角出场",
            config=config,
        )

    assert "正文内容" in result
    assert "生成正文失败" not in result
    assert "元数据稍后可重新同步" in result
    mock_db.commit.assert_called()
    mock_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_metadata_sync_success_returns_synced_note():
    from app.services.agent.chapter_tools import _generate_chapter_content_coroutine

    mock_db, _, _ = _make_db_for_new_chapter(metadata_sync_raises=False)
    config = {"configurable": {"db": mock_db, "work_id": "w-1", "emit": lambda e, d: None}}

    mock_metadata = MagicMock()
    mock_metadata.summary = "摘要"
    mock_metadata.key_plot_points = []
    mock_metadata.outline_links = []
    mock_metadata.involved_characters = []
    mock_metadata.facts = []
    mock_metadata.updated_at = None

    llm_output = "第一章\n\n正文内容。"

    with patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt, \
         patch("app.services.supervisor.sub_agent_base.get_llm") as mock_get_llm, \
         patch(
             "app.services.chapter_outline_sync_service.ChapterOutlineSyncService.generate_and_persist",
             new_callable=AsyncMock,
         ) as mock_sync:
        mock_pt.from_template.return_value = _make_llm_chain_mock(llm_output)
        mock_get_llm.return_value = MagicMock()
        mock_sync.return_value = mock_metadata

        result = await _generate_chapter_content_coroutine(
            chapter_number=1,
            chapter_brief="写第一章：主角出场",
            config=config,
        )

    assert "正文内容" in result
    assert "已自动同步章节元数据" in result
    assert "元数据稍后可重新同步" not in result
