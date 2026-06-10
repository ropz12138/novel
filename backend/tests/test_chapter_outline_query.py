"""Tests for chapter agent outline query tools (meso_doc / micro_doc).

ChapterAgent uses query_meso_outline and query_micro_outline which return
natural language documents (meso_doc / micro_doc) without requiring parameters.
"""

import sys
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, "/root/Novel/backend")


def _make_config(work_id="w1", meso_doc=None, micro_doc=None):
    """Build a RunnableConfig with mocked DB and Work."""
    work = MagicMock()
    work.id = work_id
    work.meso_doc = meso_doc
    work.micro_doc = micro_doc

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = work

    return {
        "configurable": {
            "db": db,
            "work_id": work_id,
            "emit": lambda *a, **kw: None,
        }
    }


# ── Tool registration tests ──


class TestChapterAgentToolRegistration:
    """Verify ChapterAgent has meso/micro tools but NOT macro/combined."""

    def test_chapter_agent_has_query_meso_outline(self):
        from app.services.supervisor.tool_registry import build_chapter_agent_tools

        names = {t.name for t in build_chapter_agent_tools(enable_child_todolist=False)}
        assert "query_meso_outline" in names

    def test_chapter_agent_has_query_micro_outline(self):
        from app.services.supervisor.tool_registry import build_chapter_agent_tools

        names = {t.name for t in build_chapter_agent_tools(enable_child_todolist=False)}
        assert "query_micro_outline" in names

    def test_chapter_agent_does_not_have_query_outline(self):
        from app.services.supervisor.tool_registry import build_chapter_agent_tools

        names = {t.name for t in build_chapter_agent_tools(enable_child_todolist=False)}
        assert "query_outline" not in names

    def test_chapter_agent_does_not_have_query_chapter_outline(self):
        from app.services.supervisor.tool_registry import build_chapter_agent_tools

        names = {t.name for t in build_chapter_agent_tools(enable_child_todolist=False)}
        assert "query_chapter_outline" not in names


# ── query_meso_outline functional tests ──


class TestQueryMesoOutline:
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
        assert "暂无中纲" in result

    def test_no_parameters_required(self):
        from app.services.agent.chapter_tools import query_meso_outline
        schema = query_meso_outline.args_schema
        for name, field in schema.model_fields.items():
            if name == "config":
                continue
            assert field.is_required() is False, f"Field {name} should be optional"


# ── query_micro_outline functional tests ──


class TestQueryMicroOutline:
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
        assert "暂无小纲" in result

    def test_no_parameters_required(self):
        from app.services.agent.chapter_tools import query_micro_outline
        schema = query_micro_outline.args_schema
        for name, field in schema.model_fields.items():
            if name == "config":
                continue
            assert field.is_required() is False, f"Field {name} should be optional"
