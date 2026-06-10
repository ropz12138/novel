"""Tests for the three-layer outline architecture:

1. Macro outline generation produces macro_phases + meso_stages (overview)
2. Meso doc: natural language document stored in meso_doc column
3. Micro doc: natural language document stored in micro_doc column
4. Chapter Agent queries: query_meso_outline / query_micro_outline return docs
5. Supervisor queries: query_macro_outline / query_meso_outline / query_micro_outline
"""

import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, "/root/Novel/backend")


# ── Database schema tests ──


class TestDatabaseSchema:
    """Verify meso_doc and micro_doc columns exist on Work model."""

    def test_work_model_has_meso_doc_column(self):
        from app.models.work_model import Work
        col = Work.__table__.c.get("meso_doc")
        assert col is not None, "Work model should have meso_doc column"

    def test_work_model_has_micro_doc_column(self):
        from app.models.work_model import Work
        col = Work.__table__.c.get("micro_doc")
        assert col is not None, "Work model should have micro_doc column"

    def test_meso_doc_is_nullable_text(self):
        from app.models.work_model import Work
        col = Work.__table__.c.get("meso_doc")
        assert col is not None
        assert col.nullable is True

    def test_micro_doc_is_nullable_text(self):
        from app.models.work_model import Work
        col = Work.__table__.c.get("micro_doc")
        assert col is not None
        assert col.nullable is True


# ── Chapter Agent tool registration tests ──


class TestChapterAgentTools:
    """ChapterAgent should have meso/micro doc query tools, not macro."""

    def test_has_query_meso_outline(self):
        from app.services.supervisor.tool_registry import build_chapter_agent_tools
        names = {t.name for t in build_chapter_agent_tools(enable_child_todolist=False)}
        assert "query_meso_outline" in names

    def test_has_query_micro_outline(self):
        from app.services.supervisor.tool_registry import build_chapter_agent_tools
        names = {t.name for t in build_chapter_agent_tools(enable_child_todolist=False)}
        assert "query_micro_outline" in names

    def test_does_not_have_query_outline(self):
        from app.services.supervisor.tool_registry import build_chapter_agent_tools
        names = {t.name for t in build_chapter_agent_tools(enable_child_todolist=False)}
        assert "query_outline" not in names

    def test_does_not_have_query_chapter_outline(self):
        from app.services.supervisor.tool_registry import build_chapter_agent_tools
        names = {t.name for t in build_chapter_agent_tools(enable_child_todolist=False)}
        assert "query_chapter_outline" not in names


# ── Chapter Agent query_meso_outline functional tests ──


def _make_config(work_id="w1", meso_doc=None, micro_doc=None, outline_tree=None):
    """Build a RunnableConfig with mocked DB and Work."""
    work = MagicMock()
    work.id = work_id
    work.meso_doc = meso_doc
    work.micro_doc = micro_doc
    work.outline_tree = outline_tree or {}

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = work

    return {
        "configurable": {
            "db": db,
            "work_id": work_id,
            "emit": lambda *a, **kw: None,
        }
    }


class TestQueryMesoOutlineDoc:
    """query_meso_outline returns the full meso_doc text."""

    def test_returns_meso_doc_content(self):
        from app.services.agent.chapter_tools import query_meso_outline

        doc = "## 当前阶段：战争篇\n\n主角正在与魔王军交战，主要战场在北方荒原..."
        result = query_meso_outline.invoke(
            input={},
            config=_make_config(meso_doc=doc),
        )
        assert "战争篇" in result
        assert "北方荒原" in result

    def test_returns_fallback_when_no_doc(self):
        from app.services.agent.chapter_tools import query_meso_outline

        result = query_meso_outline.invoke(
            input={},
            config=_make_config(meso_doc=None),
        )
        assert "暂无中纲" in result or "未生成" in result

    def test_no_parameters_required(self):
        """Verify the tool's input schema has no required fields."""
        from app.services.agent.chapter_tools import query_meso_outline
        schema = query_meso_outline.args_schema
        fields = schema.model_fields
        for name, field in fields.items():
            if name == "config":
                continue
            assert field.is_required() is False, f"Field {name} should be optional"


class TestQueryMicroOutlineDoc:
    """query_micro_outline returns the full micro_doc text."""

    def test_returns_micro_doc_content(self):
        from app.services.agent.chapter_tools import query_micro_outline

        doc = "## 近期场景安排\n\n### 第5章\n- 场景1：主角进入地下城\n- 场景2：遭遇陷阱"
        result = query_micro_outline.invoke(
            input={},
            config=_make_config(micro_doc=doc),
        )
        assert "第5章" in result
        assert "地下城" in result

    def test_returns_fallback_when_no_doc(self):
        from app.services.agent.chapter_tools import query_micro_outline

        result = query_micro_outline.invoke(
            input={},
            config=_make_config(micro_doc=None),
        )
        assert "暂无小纲" in result or "未生成" in result

    def test_no_parameters_required(self):
        """Verify the tool's input schema has no required fields."""
        from app.services.agent.chapter_tools import query_micro_outline
        schema = query_micro_outline.args_schema
        fields = schema.model_fields
        for name, field in fields.items():
            if name == "config":
                continue
            assert field.is_required() is False, f"Field {name} should be optional"


# ── Supervisor query tools tests ──


class TestSupervisorQueryTools:
    """Supervisor should have three separate outline query tools."""

    def test_has_query_macro_outline(self):
        from app.services.supervisor.tools import SUPERVISOR_QUERY_TOOLS
        names = {t.name for t in SUPERVISOR_QUERY_TOOLS}
        assert "query_macro_outline" in names, (
            f"query_macro_outline should be in supervisor query tools, got: {sorted(names)}"
        )

    def test_has_query_meso_outline(self):
        from app.services.supervisor.tools import SUPERVISOR_QUERY_TOOLS
        names = {t.name for t in SUPERVISOR_QUERY_TOOLS}
        assert "query_meso_outline" in names

    def test_has_query_micro_outline(self):
        from app.services.supervisor.tools import SUPERVISOR_QUERY_TOOLS
        names = {t.name for t in SUPERVISOR_QUERY_TOOLS}
        assert "query_micro_outline" in names

    def test_does_not_have_old_query_chapter_outline(self):
        from app.services.supervisor.tools import SUPERVISOR_QUERY_TOOLS
        names = {t.name for t in SUPERVISOR_QUERY_TOOLS}
        assert "query_chapter_outline" not in names
