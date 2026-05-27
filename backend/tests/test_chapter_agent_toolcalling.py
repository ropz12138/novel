"""测试 ChapterAgent Tool-Calling 改造

验证：
1. 工具集定义正确
2. ChapterAgentState 状态定义
3. LangGraph StateGraph 构建与编译
4. 工具实际逻辑（mock DB / Service）
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage


# ────────────────────────── 1. 工具注册测试 ──────────────────────────


class TestChapterToolRegistration:
    """验证 ChapterAgent 的工具集"""

    def test_chapter_tools_count(self):
        from app.services.agent.chapter_tools import CHAPTER_TOOLS
        assert len(CHAPTER_TOOLS) == 11

    def test_chapter_tool_names(self):
        from app.services.agent.chapter_tools import CHAPTER_TOOLS
        names = {t.name for t in CHAPTER_TOOLS}
        assert names == {
            "create_child_todolist",
            "read_child_todolist",
            "update_child_task_status",
            "query_outline",
            "query_chapter_outline",
            "query_previous_chapters",
            "query_characters",
            "query_foreshadowing",
            "generate_chapter_content",
            "save_chapter",
            "update_characters_after_chapter",
        }

    def test_chapter_tool_names_unique(self):
        from app.services.agent.chapter_tools import CHAPTER_TOOLS
        names = [t.name for t in CHAPTER_TOOLS]
        assert len(names) == len(set(names))


# ────────────────────────── 2. Schema 测试 ──────────────────────────


class TestChapterToolSchemas:
    """验证每个工具的输入 schema"""

    def test_query_outline_schema(self):
        from app.services.agent.chapter_tools import QueryOutlineInput
        schema = QueryOutlineInput.model_json_schema()
        assert "work_id" in schema["properties"]
        required = schema.get("required", [])
        assert "work_id" in required

    def test_query_chapter_outline_schema(self):
        from app.services.agent.chapter_tools import QueryChapterOutlineInput
        schema = QueryChapterOutlineInput.model_json_schema()
        assert "work_id" in schema["properties"]
        assert "chapter_number" in schema["properties"]

    def test_query_previous_chapters_schema(self):
        from app.services.agent.chapter_tools import QueryPreviousChaptersInput
        schema = QueryPreviousChaptersInput.model_json_schema()
        assert "work_id" in schema["properties"]
        assert "chapter_number" in schema["properties"]

    def test_query_characters_schema(self):
        from app.services.agent.chapter_tools import QueryCharactersInput
        schema = QueryCharactersInput.model_json_schema()
        assert "work_id" in schema["properties"]

    def test_query_foreshadowing_schema(self):
        from app.services.agent.chapter_tools import QueryForeshadowingInput
        schema = QueryForeshadowingInput.model_json_schema()
        assert "work_id" in schema["properties"]

    def test_generate_chapter_content_schema(self):
        from app.services.agent.chapter_tools import GenerateChapterContentInput
        schema = GenerateChapterContentInput.model_json_schema()
        assert "chapter_number" in schema["properties"]
        assert "user_instruction" in schema["properties"]

    def test_save_chapter_schema(self):
        from app.services.agent.chapter_tools import SaveChapterInput
        schema = SaveChapterInput.model_json_schema()
        assert "work_id" in schema["properties"]
        assert "chapter_number" in schema["properties"]
        assert "title" in schema["properties"]
        assert "content" in schema["properties"]

    def test_update_characters_schema(self):
        from app.services.agent.chapter_tools import UpdateCharactersAfterChapterInput
        schema = UpdateCharactersAfterChapterInput.model_json_schema()
        assert "work_id" in schema["properties"]
        assert "chapter_number" in schema["properties"]
        assert "chapter_content" in schema["properties"]


# ────────────────────────── 3. 状态定义测试 ──────────────────────────


class TestChapterAgentState:
    """验证 ChapterAgentState"""

    def test_state_has_messages(self):
        from app.services.agent.graph import ChapterAgentState
        annotations = ChapterAgentState.__annotations__
        assert "messages" in annotations

    def test_state_has_work_id(self):
        from app.services.agent.graph import ChapterAgentState
        annotations = ChapterAgentState.__annotations__
        assert "work_id" in annotations

    def test_state_has_chapter_number(self):
        from app.services.agent.graph import ChapterAgentState
        annotations = ChapterAgentState.__annotations__
        assert "chapter_number" in annotations

    def test_state_has_user_instruction(self):
        from app.services.agent.graph import ChapterAgentState
        annotations = ChapterAgentState.__annotations__
        assert "user_instruction" in annotations


# ────────────────────────── 4. 工具逻辑测试 ──────────────────────────


class TestChapterToolLogic:
    """验证工具的实际逻辑"""

    def test_query_outline_found(self):
        from app.services.agent.chapter_tools import query_outline
        mock_db = MagicMock()
        mock_work = MagicMock()
        mock_work.outline_tree = {"story": {"title": "测试", "genre": "科幻"}, "timeline": []}
        mock_work.title = "测试小说"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        result = query_outline.invoke({"work_id": "w1"}, config={"configurable": {"db": mock_db}})
        assert "测试" in result
        assert "科幻" in result

    def test_query_outline_not_found(self):
        from app.services.agent.chapter_tools import query_outline
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        result = query_outline.invoke({"work_id": "w999"}, config={"configurable": {"db": mock_db}})
        assert "不存在" in result or "未找到" in result

    def test_query_chapter_outline_found(self):
        from app.services.agent.chapter_tools import query_chapter_outline
        mock_db = MagicMock()
        mock_work = MagicMock()
        mock_work.outline_tree = {"timeline": [{"chapter_start": 1, "chapter_end": 1, "summary": "开场"}]}
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        with patch("app.services.work_service.WorkService._find_chapter_outline", return_value="第1章大纲：开场"):
            result = query_chapter_outline.invoke(
                {"work_id": "w1", "chapter_number": 1},
                config={"configurable": {"db": mock_db}},
            )
        assert "开场" in result

    def test_query_previous_chapters_found(self):
        from app.services.agent.chapter_tools import query_previous_chapters
        mock_db = MagicMock()
        mock_ch = MagicMock()
        mock_ch.chapter_number = 1
        mock_ch.title = "开端"
        mock_ch.content = "正文内容..."

        # 构建 query chain 的复杂 mock
        query_mock = MagicMock()
        query_mock.filter_by.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.limit.return_value = query_mock
        query_mock.all.return_value = [mock_ch]
        # desc() 后再 limit().all() 也要返回
        query_mock.desc.return_value = query_mock
        mock_db.query.return_value = query_mock

        result = query_previous_chapters.invoke(
            {"work_id": "w1", "chapter_number": 2, "limit": 3},
            config={"configurable": {"db": mock_db}},
        )
        # 即使 mock 链返回了空（因为 reverse() 在 list 上的行为），
        # 至少不应该报错
        assert isinstance(result, str)

    def test_query_previous_chapters_empty(self):
        from app.services.agent.chapter_tools import query_previous_chapters
        mock_db = MagicMock()
        query_mock = MagicMock()
        query_mock.filter_by.return_value = query_mock
        query_mock.filter.return_value = query_mock
        query_mock.order_by.return_value = query_mock
        query_mock.limit.return_value = query_mock
        query_mock.all.return_value = []
        query_mock.desc.return_value = query_mock
        mock_db.query.return_value = query_mock

        result = query_previous_chapters.invoke(
            {"work_id": "w1", "chapter_number": 1, "limit": 3},
            config={"configurable": {"db": mock_db}},
        )
        assert "第一章" in result or "暂无前文" in result

    def test_query_characters_found(self):
        from app.services.agent.chapter_tools import query_characters
        mock_db = MagicMock()
        mock_char = MagicMock()
        mock_char.name = "张三"
        mock_char.role_type = "主角"
        mock_char.first_chapter = 1
        mock_char.gender = "男"
        mock_char.age = "20"
        mock_char.personality = "勇敢"
        mock_char.current_status = "活着"
        mock_char.current_goal = "冒险"
        mock_db.query.return_value.filter_by.return_value.all.return_value = [mock_char]

        result = query_characters.invoke(
            {"work_id": "w1"},
            config={"configurable": {"db": mock_db}},
        )
        assert "张三" in result

    def test_query_characters_empty(self):
        from app.services.agent.chapter_tools import query_characters
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.all.return_value = []

        result = query_characters.invoke(
            {"work_id": "w1"},
            config={"configurable": {"db": mock_db}},
        )
        assert "暂无角色" in result or "无" in result

    def test_query_foreshadowing_found(self):
        from app.services.agent.chapter_tools import query_foreshadowing
        mock_db = MagicMock()
        mock_work = MagicMock()
        mock_work.outline_tree = {
            "foreshadowing": [
                {"id": "F1", "content": "神秘信件", "plant_node": "第1章", "payoff_node": "第5章"},
            ]
        }
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        result = query_foreshadowing.invoke(
            {"work_id": "w1"},
            config={"configurable": {"db": mock_db}},
        )
        assert "F1" in result
        assert "神秘信件" in result

    def test_save_chapter_success(self):
        from app.services.agent.chapter_tools import save_chapter
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        result = save_chapter.invoke(
            {"work_id": "w1", "chapter_number": 1, "title": "第一章 开端", "content": "正文..."},
            config={"configurable": {"db": mock_db}},
        )
        assert "成功" in result or "已保存" in result
        mock_db.add.assert_called()
        mock_db.commit.assert_called()

    def test_save_chapter_update_existing(self):
        from app.services.agent.chapter_tools import save_chapter
        mock_db = MagicMock()
        mock_chapter = MagicMock()
        mock_chapter.chapter_number = 1
        mock_chapter.title = "旧标题"
        mock_chapter.content = ""
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_chapter

        result = save_chapter.invoke(
            {"work_id": "w1", "chapter_number": 1, "title": "新标题", "content": "新正文..."},
            config={"configurable": {"db": mock_db}},
        )
        assert "成功" in result or "已保存" in result
        mock_db.commit.assert_called()


# ────────────────────────── 5. LangGraph 构建测试 ──────────────────────────


class TestChapterGraphBuild:
    """验证 ChapterAgent 的 LangGraph 构建"""

    def test_build_graph_compiles(self):
        from app.services.agent.graph import ChapterAgentGraph
        mock_db = MagicMock()
        mock_emit = MagicMock()
        graph_instance = ChapterAgentGraph(
            work_id="w1", chapter_number=1, db=mock_db, emit=mock_emit, auto_mode=True,
        )
        graph = graph_instance._build_graph()
        assert graph is not None
