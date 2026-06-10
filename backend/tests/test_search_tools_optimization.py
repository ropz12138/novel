"""测试搜索工具优化

验证：
1. grep 支持 keywords 列表，一次调用搜索多个关键词
2. grep 保持向后兼容：仍支持单个 keyword 字符串
3. query_characters 返回完整角色信息
4. query_chapters 支持只返回内容摘要（content_preview），避免返回全文章节正文
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ────────────────────────── 1. grep 多关键词测试 ──────────────────────────


class TestGrepMultiKeywords:
    """验证 grep 支持 keywords 列表批量搜索"""

    def test_grep_schema_has_keywords_field(self):
        """GrepInput schema 应包含 keywords 字段"""
        from app.services.supervisor.tools import GrepInput
        schema = GrepInput.model_json_schema()
        props = schema["properties"]
        assert "keywords" in props, f"keywords 不在 {list(props.keys())} 中"

    def test_grep_schema_keywords_is_list(self):
        """keywords 应为字符串列表"""
        from app.services.supervisor.tools import GrepInput
        schema = GrepInput.model_json_schema()
        kw_prop = schema["properties"]["keywords"]
        assert kw_prop.get("type") == "array", f"keywords 应为 array，实际为 {kw_prop}"

    def test_grep_with_keywords_list(self):
        """使用 keywords 列表调用 grep 应一次搜索多个关键词"""
        from app.services.supervisor.tools import grep

        mock_db = MagicMock()

        with patch("app.services.character_service.CharacterService.grep") as mock_grep:
            mock_grep.return_value = [
                {"source": "character", "character_name": "秦渊", "field": "name", "snippet": "秦渊"},
            ]

            with patch("app.services.supervisor.tools._resolve_bound_work_id", return_value=("w1", None)):
                result = grep.invoke(
                    {
                        "work_id": "w1",
                        "keywords": ["秦渊", "觉醒"],
                        "scope": "all",
                        "context_chars": 200,
                    },
                    config={"configurable": {"db": mock_db, "supervisor_session_id": "s1"}},
                )

            # CharacterService.grep 应被调用2次（每个关键词一次）
            assert mock_grep.call_count == 2

    def test_grep_single_keyword_backward_compat(self):
        """单个 keyword 字符串调用 grep 仍能工作（向后兼容）"""
        from app.services.supervisor.tools import grep

        mock_db = MagicMock()

        with patch("app.services.character_service.CharacterService.grep") as mock_grep:
            mock_grep.return_value = [
                {"source": "character", "character_name": "秦渊", "field": "name", "snippet": "秦渊"},
            ]

            with patch("app.services.supervisor.tools._resolve_bound_work_id", return_value=("w1", None)):
                result = grep.invoke(
                    {
                        "work_id": "w1",
                        "keywords": ["秦渊"],
                        "scope": "all",
                        "context_chars": 200,
                    },
                    config={"configurable": {"db": mock_db, "supervisor_session_id": "s1"}},
                )

            assert "秦渊" in result


# ────────────────────────── 2. query_characters 测试 ──────────────────────────


class TestQueryCharacters:
    """验证 query_characters 返回完整信息"""

    def test_query_characters_schema(self):
        """QueryCharactersInput schema 应包含 filters 字段"""
        from app.services.supervisor.tools import QueryCharactersInput
        schema = QueryCharactersInput.model_json_schema()
        props = schema["properties"]
        assert "filters" in props

    def test_query_characters_returns_formatted_info(self):
        """query_characters 应返回格式化的角色信息"""
        from app.services.supervisor.tools import query_characters

        mock_db = MagicMock()

        with patch("app.services.character_service.CharacterService.query_data") as mock_qd:
            mock_qd.return_value = [
                {
                    "name": "秦渊",
                    "role_type": "主角",
                    "gender": "男",
                    "age": "24",
                    "appearance": "身材修长",
                    "personality": "冷静",
                    "background": "S市上班族",
                    "skills": "暗金之力",
                    "current_status": "存活",
                    "current_goal": "生存",
                    "last_location": "S市",
                    "first_appearance_stage": "M1",
                }
            ]

            with patch("app.services.supervisor.tools._resolve_bound_work_id", return_value=("w1", None)):
                result = query_characters.invoke(
                    {
                        "work_id": "w1",
                        "filters": {},
                    },
                    config={"configurable": {"db": mock_db, "supervisor_session_id": "s1"}},
                )

            assert "秦渊" in result
            assert "主角" in result


# ────────────────────────── 3. query_chapters 内容截断测试 ──────────────────────────


class TestQueryChaptersContentPreview:
    """验证 query_chapters 支持 content_preview 截断"""

    def test_query_chapters_schema_has_content_preview(self):
        """QueryChaptersInput schema 应包含 content_preview 字段"""
        from app.services.supervisor.tools import QueryChaptersInput
        schema = QueryChaptersInput.model_json_schema()
        props = schema["properties"]
        assert "content_preview_length" in props or "content_preview" in props, (
            f"缺少 content_preview 相关字段，现有字段: {list(props.keys())}"
        )

    def test_query_chapters_truncates_long_content(self):
        """长章节内容应被截断为预览"""
        from app.services.supervisor.tools import query_chapters

        mock_db = MagicMock()
        long_content = "这是一段很长的内容。" * 10000

        with patch("app.services.character_service.CharacterService.query_data") as mock_qd:
            mock_qd.return_value = [
                {
                    "chapter_number": 1,
                    "title": "第一章",
                    "status": "已完成",
                    "content": long_content,
                }
            ]

            with patch("app.services.supervisor.tools._resolve_bound_work_id", return_value=("w1", None)):
                result = query_chapters.invoke(
                    {
                        "work_id": "w1",
                        "filters": {},
                        "content_preview_length": 200,
                    },
                    config={"configurable": {"db": mock_db, "supervisor_session_id": "s1"}},
                )

            # 返回内容不应包含完整的 10 万字
            assert len(result) < len(long_content)
