"""Remove foreshadow query tool and chapter metadata foreshadows field."""

import sys

sys.path.insert(0, "/root/Novel/backend")


class TestQueryForeshadowingUnregistered:
    def test_not_in_chapter_agent_tools(self):
        from app.services.supervisor.tool_registry import build_chapter_agent_tools

        names = {t.name for t in build_chapter_agent_tools(enable_child_todolist=False)}
        assert "query_foreshadowing" not in names

    def test_not_in_supervisor_query_tools(self):
        from app.services.supervisor.tools import SUPERVISOR_QUERY_TOOLS

        names = {t.name for t in SUPERVISOR_QUERY_TOOLS}
        assert "query_foreshadowing" not in names


class TestChapterMetadataNoForeshadows:
    def test_output_schema_has_no_foreshadows(self):
        from app.services.chapter_outline_sync_service import ChapterMetadataOutput

        assert "foreshadows" not in ChapterMetadataOutput.model_fields

    def test_chapter_metadata_model_has_no_foreshadows_column(self):
        from app.models.work_model import ChapterMetadata

        assert "foreshadows" not in ChapterMetadata.__table__.columns.keys()


class TestForeshadowsColumnMigration:
    def test_ensure_columns_drops_foreshadows_column(self):
        import inspect

        from app.core import database

        src = inspect.getsource(database._ensure_columns)
        assert "DROP COLUMN foreshadows" in src
