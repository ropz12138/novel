"""测试 count_chapter_words 工具

验证：
1. 正常返回章节字数
2. 章节不存在时的处理
3. 章节内容为空时的处理
4. 字数统计规则（去除空白和换行）
"""

import pytest
from unittest.mock import MagicMock

from langchain_core.runnables import RunnableConfig


class TestCountChapterWords:
    """验证 count_chapter_words 工具"""

    def _make_config(self, mock_db, work_id="w1"):
        return {"configurable": {"db": mock_db, "bound_work_id": work_id}}

    def test_returns_word_count_for_existing_chapter(self):
        from app.services.supervisor.tools import count_chapter_words

        mock_db = MagicMock()
        mock_chapter = MagicMock()
        mock_chapter.content = "这是一段测试文字，共有若干个字。"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_chapter

        result = count_chapter_words.invoke(
            {"chapter_number": 1, "work_id": "w1"},
            config=self._make_config(mock_db),
        )
        assert "字数" in result
        assert "16" in result  # 去除空格和换行后的字数（含标点）

    def test_chapter_not_found(self):
        from app.services.supervisor.tools import count_chapter_words

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        result = count_chapter_words.invoke(
            {"chapter_number": 99, "work_id": "w1"},
            config=self._make_config(mock_db),
        )
        assert "不存在" in result or "未找到" in result

    def test_empty_content(self):
        from app.services.supervisor.tools import count_chapter_words

        mock_db = MagicMock()
        mock_chapter = MagicMock()
        mock_chapter.content = ""
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_chapter

        result = count_chapter_words.invoke(
            {"chapter_number": 1, "work_id": "w1"},
            config=self._make_config(mock_db),
        )
        assert "0" in result

    def test_strips_whitespace_and_newlines(self):
        from app.services.supervisor.tools import count_chapter_words

        mock_db = MagicMock()
        mock_chapter = MagicMock()
        mock_chapter.content = "  \n  你好世界  \n  "
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_chapter

        result = count_chapter_words.invoke(
            {"chapter_number": 1, "work_id": "w1"},
            config=self._make_config(mock_db),
        )
        assert "4" in result  # 你好世界 = 4个字

    def test_work_id_from_config_when_not_provided(self):
        from app.services.supervisor.tools import count_chapter_words

        mock_db = MagicMock()
        mock_chapter = MagicMock()
        mock_chapter.content = "测试"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_chapter

        result = count_chapter_words.invoke(
            {"chapter_number": 1},
            config={"configurable": {"db": mock_db, "work_id": "w1"}},
        )
        assert "字数" in result

    def test_tool_registered_in_all_tools(self):
        from app.services.supervisor.tools import ALL_TOOLS
        names = {t.name for t in ALL_TOOLS}
        assert "count_chapter_words" in names

    def test_tool_registered_in_chapter_agent_tools(self):
        from app.services.supervisor.chapter_agent import CHAPTER_AGENT_TOOLS
        names = {t.name for t in CHAPTER_AGENT_TOOLS}
        assert "count_chapter_words" in names
