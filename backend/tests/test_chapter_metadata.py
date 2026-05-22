from unittest.mock import MagicMock

from app.services.chapter_outline_sync_service import ChapterMetadataOutput, ChapterOutlineSyncService


def test_chapter_metadata_output_defaults():
    data = ChapterMetadataOutput()
    assert data.summary == ""
    assert data.key_plot_points == []
    assert data.outline_links == []


def test_persist_metadata_upsert():
    mock_db = MagicMock()

    # first(): missing then existing row flow
    missing_query = MagicMock()
    missing_query.filter_by.return_value.first.return_value = None
    mock_db.query.return_value = missing_query

    row = ChapterOutlineSyncService.persist_metadata(
        mock_db,
        work_id="w1",
        chapter_number=1,
        metadata=ChapterMetadataOutput(
            summary="摘要",
            key_plot_points=["a"],
        ),
    )

    assert row.summary == "摘要"
    assert row.key_plot_points == ["a"]
