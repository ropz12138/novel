"""Tests for submit outline tools: reject empty/invalid data instead of silently persisting."""

import pytest
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, "/root/Novel/backend")


def _make_ctx(*, has_work: bool = False):
    mock_db = MagicMock()
    mock_work = MagicMock()
    mock_work.id = "w-1"
    mock_work.outline_tree = {}
    mock_work.title = "旧标题"
    mock_work.meso_doc = None
    mock_work.micro_doc = None

    if has_work:
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work
    else:
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

    return {
        "db": mock_db,
        "user_id": "u-1",
        "idea": "test idea",
        "tags_list": [],
        "work_id": "w-1" if has_work else None,
    }, mock_db, mock_work


class TestSubmitMacroOutlineRejectsEmptyData:

    @patch("app.services.work_service._outline_ctx")
    def test_rejects_empty_macro_phases(self, mock_ctx):
        from app.services.work_service import _submit_macro_outline_tool

        ctx, mock_db, _ = _make_ctx()
        mock_ctx.return_value = ctx

        with pytest.raises(ValueError, match="macro_phases"):
            _submit_macro_outline_tool(
                story={"title": "测试", "genre": "测试"},
                macro_phases=[],
                core_characters=[{"name": "A", "role_type": "主角", "brief": "xx"}],
                ending={},
            )
        mock_db.commit.assert_not_called()

    @patch("app.services.work_service._outline_ctx")
    def test_rejects_empty_core_characters(self, mock_ctx):
        from app.services.work_service import _submit_macro_outline_tool

        ctx, mock_db, _ = _make_ctx()
        mock_ctx.return_value = ctx

        with pytest.raises(ValueError, match="core_characters"):
            _submit_macro_outline_tool(
                story={"title": "测试", "genre": "测试"},
                macro_phases=[{"id": "P1", "name": "阶段1", "goal": "g", "core_setting": "s", "chapter_range": [1, 5]}],
                core_characters=[],
                ending={},
            )
        mock_db.commit.assert_not_called()

    @patch("app.services.work_service._outline_ctx")
    def test_rejects_empty_story(self, mock_ctx):
        from app.services.work_service import _submit_macro_outline_tool

        ctx, mock_db, _ = _make_ctx()
        mock_ctx.return_value = ctx

        with pytest.raises(ValueError, match="story"):
            _submit_macro_outline_tool(
                story={},
                macro_phases=[{"id": "P1", "name": "阶段1", "goal": "g", "core_setting": "s", "chapter_range": [1, 5]}],
                core_characters=[{"name": "A", "role_type": "主角", "brief": "xx"}],
                ending={},
            )
        mock_db.commit.assert_not_called()

    @patch("app.services.work_service._outline_ctx")
    def test_rejects_nested_args(self, mock_ctx):
        from app.services.work_service import _submit_macro_outline_tool

        ctx, mock_db, _ = _make_ctx()
        mock_ctx.return_value = ctx

        with pytest.raises(ValueError, match="story|macro_phases|core_characters"):
            _submit_macro_outline_tool(
                macro_outline={
                    "story": {"title": "测试"},
                    "macro_phases": [{"id": "P1"}],
                    "core_characters": [{"name": "A"}],
                },
            )
        mock_db.commit.assert_not_called()


class TestSubmitMesoOutlineRejectsEmptyData:

    @patch("app.services.work_service._outline_ctx")
    def test_rejects_empty_meso_doc(self, mock_ctx):
        from app.services.work_service import _submit_meso_outline_tool

        ctx, mock_db, _ = _make_ctx(has_work=True)
        mock_ctx.return_value = ctx

        with pytest.raises(ValueError, match="meso_doc"):
            _submit_meso_outline_tool(meso_doc="")
        mock_db.commit.assert_not_called()


class TestSubmitMicroOutlineRejectsEmptyData:

    @patch("app.services.work_service._outline_ctx")
    def test_rejects_empty_micro_doc(self, mock_ctx):
        from app.services.work_service import _submit_micro_outline_tool

        ctx, mock_db, _ = _make_ctx(has_work=True)
        mock_ctx.return_value = ctx

        with pytest.raises(ValueError, match="micro_doc"):
            _submit_micro_outline_tool(micro_doc="")
        mock_db.commit.assert_not_called()
