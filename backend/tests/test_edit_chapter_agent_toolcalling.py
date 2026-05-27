"""测试 EditChapterAgent Tool-Calling 工具集（重构后）"""

import pytest
from unittest.mock import MagicMock, patch


class TestEditChapterToolRegistration:
    def test_edit_chapter_tools_count(self):
        from app.services.supervisor.edit_chapter_tools import EDIT_CHAPTER_TOOLS
        assert len(EDIT_CHAPTER_TOOLS) == 12

    def test_edit_chapter_tool_names(self):
        from app.services.supervisor.edit_chapter_tools import EDIT_CHAPTER_TOOLS
        names = {t.name for t in EDIT_CHAPTER_TOOLS}
        assert names == {
            "create_child_todolist",
            "read_child_todolist",
            "update_child_task_status",
            "read_chapter",
            "query_characters_by_chapter",
            "grep_in_chapter",
            "query_chapter_meta",
            "grep_chapter_meta",
            "generate_patch_edit",
            "rewrite_chapter",
            "overwrite_chapter_title",
            "sync_chapter_metadata",
        }


class TestEditChapterToolSchemas:
    def test_rewrite_chapter_schema(self):
        from app.services.supervisor.edit_chapter_tools import RewriteChapterInput

        schema = RewriteChapterInput.model_json_schema()
        required = schema.get("required", [])
        assert "work_id" in required
        assert "chapter_number" in required
        assert "current_content" in required
        assert "edit_instruction" in required

    def test_generate_patch_edit_schema(self):
        from app.services.supervisor.edit_chapter_tools import GeneratePatchEditInput

        schema = GeneratePatchEditInput.model_json_schema()
        required = schema.get("required", [])
        assert "work_id" in required
        assert "chapter_number" in required
        assert "current_content" in required
        assert "edit_instruction" in required


class TestQueryTools:
    def test_query_chapter_meta_no_data(self):
        from app.services.supervisor.edit_chapter_tools import query_chapter_meta

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        result = query_chapter_meta.invoke(
            {"work_id": "w1", "chapter_number": 1},
            config={"configurable": {"db": mock_db}},
        )
        assert "暂无元数据" in result


class TestEditChapterAgentState:
    def test_state_annotations(self):
        from app.services.supervisor.edit_chapter_agent import EditChapterState

        ann = EditChapterState.__annotations__
        assert "messages" in ann
        assert "work_id" in ann
        assert "chapter_number" in ann
        assert "user_message" in ann


@pytest.mark.asyncio
async def test_rewrite_chapter_streams_and_returns():
    from app.services.supervisor.edit_chapter_tools import rewrite_chapter

    mock_db = MagicMock()
    config = {"configurable": {"db": mock_db, "emit": lambda *_: None}}

    async def fake_astream(_input):
        chunk = MagicMock()
        chunk.content = "修改后正文"
        yield chunk

    async def fake_save_and_sync_metadata(**kwargs):
        return "已保存并同步"

    with patch("app.services.supervisor.edit_chapter_tools.PromptTemplate") as MockPT, \
         patch("app.services.supervisor.edit_chapter_tools._get_llm") as mock_llm_cls, \
         patch("app.services.supervisor.edit_chapter_tools._save_and_sync_metadata", side_effect=fake_save_and_sync_metadata):
        mock_prompt = MagicMock()
        MockPT.from_template.return_value = mock_prompt
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm

        mock_chain = MagicMock()
        mock_chain.astream = fake_astream
        mock_prompt.__or__ = MagicMock(return_value=mock_chain)

        result = await rewrite_chapter.coroutine(
            work_id="w1",
            chapter_number=1,
            current_content="旧内容",
            edit_instruction="修改开头",
            config=config,
        )

    assert "已保存并同步" in result
    assert "修改后正文" in result
