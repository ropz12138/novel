"""Tests for outline generation refactoring:
1. Macro submit now accepts meso_stages and saves them to outline_tree
2. Meso generate produces natural language meso_doc
3. Micro generate produces natural language micro_doc
"""

import pytest
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, "/root/Novel/backend")


# ── Helpers ──

def _make_ctx(*, has_work: bool = True):
    mock_db = MagicMock()
    mock_work = MagicMock()
    mock_work.id = "w-1"
    mock_work.title = "测试作品"
    mock_work.outline_tree = {
        "outline": {
            "story": {"title": "测试", "genre": "测试"},
            "macro_phases": [{"id": "P1", "name": "阶段1"}],
            "core_characters": [{"name": "A"}],
        },
    }
    mock_work.meso_doc = None
    mock_work.micro_doc = None

    if has_work:
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work
    else:
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

    return {
        "db": mock_db,
        "user_id": "u-1",
        "idea": "test",
        "tags_list": [],
        "work_id": "w-1",
    }, mock_db, mock_work


# ── Macro submit now saves meso_stages ──

class TestMacroSubmitSavesMesoStages:
    """_submit_macro_outline_tool should persist meso_stages into outline_tree."""

    @patch("app.services.work_service._outline_ctx")
    def test_saves_meso_stages_to_outline_tree(self, mock_ctx):
        from app.services.work_service import _submit_macro_outline_tool

        ctx, mock_db, mock_work = _make_ctx()
        mock_ctx.return_value = ctx

        meso_stages = [
            {"id": "M1", "macro_phase_id": "P1", "name": "中纲阶段1", "summary": "xxx"},
        ]

        _submit_macro_outline_tool(
            story={"title": "测试", "genre": "测试"},
            macro_phases=[{"id": "P1", "name": "阶段1", "goal": "g", "core_setting": "s", "chapter_range": [1, 5]}],
            core_characters=[{"name": "A", "role_type": "主角", "brief": "xx"}],
            meso_stages=meso_stages,
            ending={},
        )

        mock_db.commit.assert_called()
        saved = mock_work.outline_tree
        assert saved["outline"]["macro_phases"][0]["id"] == "P1"
        assert saved["meso"]["meso_stages"] == meso_stages


# ── Meso submit writes to meso_doc ──

class TestMesoSubmitWritesDoc:
    """_submit_meso_outline_tool should write natural language to work.meso_doc."""

    @patch("app.services.work_service._outline_ctx")
    def test_writes_meso_doc_text(self, mock_ctx):
        from app.services.work_service import _submit_meso_outline_tool

        ctx, mock_db, mock_work = _make_ctx()
        mock_ctx.return_value = ctx

        doc_text = "当前处于第一阶段「雨夜之门」。苏晚走投无路，敲开了萧夜的门..."

        _submit_meso_outline_tool(meso_doc=doc_text)

        mock_db.commit.assert_called()
        assert mock_work.meso_doc == doc_text

    @patch("app.services.work_service._outline_ctx")
    def test_rejects_empty_meso_doc(self, mock_ctx):
        from app.services.work_service import _submit_meso_outline_tool

        ctx, mock_db, _ = _make_ctx()
        mock_ctx.return_value = ctx

        with pytest.raises(ValueError, match="meso_doc"):
            _submit_meso_outline_tool(meso_doc="")
        mock_db.commit.assert_not_called()


# ── Micro submit writes to micro_doc ──

class TestMicroSubmitWritesDoc:
    """_submit_micro_outline_tool should write natural language to work.micro_doc."""

    @patch("app.services.work_service._outline_ctx")
    def test_writes_micro_doc_text(self, mock_ctx):
        from app.services.work_service import _submit_micro_outline_tool

        ctx, mock_db, mock_work = _make_ctx()
        mock_ctx.return_value = ctx

        doc_text = "第1章场景：暴雨夜便利店门口，苏晚刷新论坛。第2章场景：萧夜公寓门口，交易谈判。"

        _submit_micro_outline_tool(micro_doc=doc_text)

        mock_db.commit.assert_called()
        assert mock_work.micro_doc == doc_text

    @patch("app.services.work_service._outline_ctx")
    def test_rejects_empty_micro_doc(self, mock_ctx):
        from app.services.work_service import _submit_micro_outline_tool

        ctx, mock_db, _ = _make_ctx()
        mock_ctx.return_value = ctx

        with pytest.raises(ValueError, match="micro_doc"):
            _submit_micro_outline_tool(micro_doc="")
        mock_db.commit.assert_not_called()


# ── Meso submit schema ──

class TestMesoSubmitSchema:
    def test_schema_has_meso_doc_field(self):
        from app.services.work_service import _SubmitMesoOutlineInput
        fields = _SubmitMesoOutlineInput.model_fields
        assert "meso_doc" in fields

    def test_schema_no_meso_stages_field(self):
        from app.services.work_service import _SubmitMesoOutlineInput
        fields = _SubmitMesoOutlineInput.model_fields
        assert "meso_stages" not in fields


# ── Micro submit schema ──

class TestMicroSubmitSchema:
    def test_schema_has_micro_doc_field(self):
        from app.services.work_service import _SubmitMicroOutlineInput
        fields = _SubmitMicroOutlineInput.model_fields
        assert "micro_doc" in fields

    def test_schema_no_micro_scenes_field(self):
        from app.services.work_service import _SubmitMicroOutlineInput
        fields = _SubmitMicroOutlineInput.model_fields
        assert "micro_scenes" not in fields


# ── Macro submit schema includes meso_stages ──

class TestMacroSubmitSchemaIncludesMeso:
    def test_schema_has_meso_stages(self):
        from app.services.work_service import _SubmitMacroOutlineInput
        fields = _SubmitMacroOutlineInput.model_fields
        assert "meso_stages" in fields
