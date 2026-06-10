"""Tests for the simplified generate_chapter_content interface.

After simplification:
- Only chapter_number + chapter_brief are required
- No story_info, outline_tree, chapter_outline, context_pack, previous_chapters, thinking_notes
- Prompt template only has {chapter_number} and {chapter_brief}
"""

import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "/root/Novel/backend")


class TestGenerateChapterContentSchema:
    """Verify the simplified input schema."""

    def test_only_chapter_number_and_brief_required(self):
        from app.services.agent.chapter_tools import GenerateChapterContentInput

        schema = GenerateChapterContentInput.model_json_schema()
        required = schema.get("required", [])
        assert "chapter_number" in required
        assert "chapter_brief" in required

    def test_no_story_info_field(self):
        from app.services.agent.chapter_tools import GenerateChapterContentInput

        fields = GenerateChapterContentInput.model_fields
        assert "story_info" not in fields

    def test_no_outline_tree_field(self):
        from app.services.agent.chapter_tools import GenerateChapterContentInput

        fields = GenerateChapterContentInput.model_fields
        assert "outline_tree" not in fields

    def test_no_chapter_outline_field(self):
        from app.services.agent.chapter_tools import GenerateChapterContentInput

        fields = GenerateChapterContentInput.model_fields
        assert "chapter_outline" not in fields

    def test_no_context_pack_field(self):
        from app.services.agent.chapter_tools import GenerateChapterContentInput

        fields = GenerateChapterContentInput.model_fields
        assert "context_pack" not in fields

    def test_no_previous_chapters_field(self):
        from app.services.agent.chapter_tools import GenerateChapterContentInput

        fields = GenerateChapterContentInput.model_fields
        assert "previous_chapters" not in fields

    def test_no_thinking_notes_field(self):
        from app.services.agent.chapter_tools import GenerateChapterContentInput

        fields = GenerateChapterContentInput.model_fields
        assert "thinking_notes" not in fields

    def test_no_user_instruction_field(self):
        from app.services.agent.chapter_tools import GenerateChapterContentInput

        fields = GenerateChapterContentInput.model_fields
        assert "user_instruction" not in fields


class TestPromptTemplate:
    """Verify the prompt template only has chapter_number and chapter_brief."""

    def test_template_has_chapter_number_and_brief(self):
        from pathlib import Path
        prompt_dir = Path(__file__).resolve().parents[1] / "app" / "services" / "prompt_templates"
        template = (prompt_dir / "agent_write.txt").read_text(encoding="utf-8")
        assert "{chapter_number}" in template
        assert "{chapter_brief}" in template

    def test_template_no_old_variables(self):
        from pathlib import Path
        prompt_dir = Path(__file__).resolve().parents[1] / "app" / "services" / "prompt_templates"
        template = (prompt_dir / "agent_write.txt").read_text(encoding="utf-8")
        assert "{story_info}" not in template
        assert "{outline_tree}" not in template
        assert "{chapter_outline}" not in template
        assert "{context_pack}" not in template
        assert "{previous_chapters}" not in template
        assert "{thinking_notes}" not in template


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
    mock_work.outline_tree = {}

    chapter_q = MagicMock()
    chapter_q.filter_by.return_value.first.side_effect = [None, None, None, MagicMock()]
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


class TestGenerateChapterContentFunc:
    """Verify the function works with only chapter_number + chapter_brief."""

    @pytest.mark.asyncio
    async def test_accepts_chapter_brief_only(self):
        from app.services.agent.chapter_tools import _generate_chapter_content_coroutine

        mock_db = _make_db_for_new_chapter()
        config = {"configurable": {"db": mock_db, "work_id": "w-1", "emit": lambda e, d: None}}

        llm_output = "标题：测试\n\n正文内容。"

        with patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt, \
             patch("app.services.supervisor.sub_agent_base.get_llm") as mock_get_llm, \
             patch(
                 "app.services.chapter_outline_sync_service.ChapterOutlineSyncService.generate_and_persist",
                 new_callable=AsyncMock,
             ) as mock_sync:
            mock_pt.from_template.return_value = _make_llm_chain_mock(llm_output)
            mock_get_llm.return_value = MagicMock()
            mock_sync.side_effect = RuntimeError("skip")

            result = await _generate_chapter_content_coroutine(
                chapter_number=1,
                chapter_brief="第1章：主角出场，遭遇意外事件，需要做出关键抉择。",
                config=config,
            )

        assert "正文内容" in result

    @pytest.mark.asyncio
    async def test_rejects_empty_brief(self):
        from app.services.agent.chapter_tools import _generate_chapter_content_coroutine

        mock_db = _make_db_for_new_chapter()
        config = {"configurable": {"db": mock_db, "work_id": "w-1", "emit": lambda e, d: None}}

        result = await _generate_chapter_content_coroutine(
            chapter_number=1,
            chapter_brief="",
            config=config,
        )

        assert "生成正文失败" in result
        assert "chapter_brief" in result
