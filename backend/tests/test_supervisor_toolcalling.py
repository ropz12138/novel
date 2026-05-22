"""测试 SupervisorAgent LangGraph Tool-Calling 重构

覆盖:
1. 工具注册：8 个工具是否正确创建（3 查询 + 5 派发）
2. SupervisorState 定义
3. LangGraph StateGraph 构建
4. 查询工具的单元测试（mock DB）
5. System Prompt 构建
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage


# ────────────────────────── 1. 工具注册测试 ──────────────────────────


class TestToolRegistration:
    """验证所有工具正确注册"""

    def test_all_tools_count(self):
        """应该恰好注册 9 个工具（5 查询 + 4 派发）"""
        from app.services.supervisor.tools import ALL_TOOLS
        assert len(ALL_TOOLS) == 9

    def test_query_characters_registered(self):
        from app.services.supervisor.tools import query_characters
        assert query_characters.name == "query_characters"
        assert "角色" in query_characters.description

    def test_query_chapters_registered(self):
        from app.services.supervisor.tools import query_chapters
        assert query_chapters.name == "query_chapters"
        assert "章节" in query_chapters.description

    def test_grep_registered(self):
        from app.services.supervisor.tools import grep
        assert grep.name == "grep"
        assert "搜索" in grep.description

    def test_dispatch_outline_registered(self):
        from app.services.supervisor.tools import dispatch_outline
        assert dispatch_outline.name == "dispatch_outline"
        assert dispatch_outline.coroutine is not None

    def test_dispatch_requirements_planner_registered(self):
        from app.services.supervisor.tools import dispatch_requirements_planner
        assert dispatch_requirements_planner.name == "dispatch_requirements_planner"
        assert dispatch_requirements_planner.coroutine is not None

    def test_dispatch_chapter_registered(self):
        from app.services.supervisor.tools import dispatch_chapter
        assert dispatch_chapter.name == "dispatch_chapter"
        assert dispatch_chapter.coroutine is not None

    def test_dispatch_evaluation_registered(self):
        from app.services.supervisor.tools import dispatch_evaluation
        assert dispatch_evaluation.name == "dispatch_evaluation"
        assert dispatch_evaluation.coroutine is not None

    def test_dispatch_writing_expert_registered(self):
        from app.services.supervisor.tools import dispatch_writing_expert
        assert dispatch_writing_expert.name == "dispatch_writing_expert"
        assert dispatch_writing_expert.coroutine is not None

    def test_tool_names_unique(self):
        """所有工具名不应重复"""
        from app.services.supervisor.tools import ALL_TOOLS
        names = [t.name for t in ALL_TOOLS]
        assert len(names) == len(set(names))

    def test_sync_tools_have_func(self):
        """查询类工具（sync）应有 func"""
        from app.services.supervisor.tools import query_characters, query_chapters, grep
        assert query_characters.func is not None
        assert query_chapters.func is not None
        assert grep.func is not None

    def test_async_tools_have_coroutine(self):
        """派发类工具（async）应有 coroutine"""
        from app.services.supervisor.tools import (
            dispatch_chapter,
            dispatch_evaluation,
            dispatch_outline,
            dispatch_requirements_planner,
            dispatch_writing_expert,
        )
        assert dispatch_requirements_planner.coroutine is not None
        assert dispatch_outline.coroutine is not None
        assert dispatch_chapter.coroutine is not None
        assert dispatch_evaluation.coroutine is not None
        assert dispatch_writing_expert.coroutine is not None


# ────────────────────────── 2. Tool Schema 测试 ──────────────────────────


class TestToolSchemas:
    """验证工具的输入 schema"""

    def test_query_characters_schema(self):
        from app.services.supervisor.tools import QueryCharactersInput
        schema = QueryCharactersInput.model_json_schema()
        assert "work_id" in schema["properties"]
        assert "filters" in schema["properties"]

    def test_query_chapters_schema(self):
        from app.services.supervisor.tools import QueryChaptersInput
        schema = QueryChaptersInput.model_json_schema()
        assert "work_id" in schema["properties"]
        assert "filters" in schema["properties"]

    def test_grep_schema(self):
        from app.services.supervisor.tools import GrepInput
        schema = GrepInput.model_json_schema()
        assert "work_id" in schema["properties"]
        assert "keyword" in schema["properties"]
        assert "scope" in schema["properties"]

    def test_dispatch_outline_schema(self):
        from app.services.supervisor.tools import DispatchOutlineInput
        schema = DispatchOutlineInput.model_json_schema()
        assert "message" in schema["properties"]
        assert "work_id" in schema["properties"]
        required = schema.get("required", [])
        assert "message" in required
        assert "work_id" not in required

    def test_dispatch_chapter_schema(self):
        from app.services.supervisor.tools import DispatchChapterInput
        schema = DispatchChapterInput.model_json_schema()
        assert "work_id" in schema["properties"]
        assert "instruction" in schema["properties"]
        assert "chapter_number" in schema["properties"]
        required = schema.get("required", [])
        assert "work_id" in required
        assert "chapter_number" not in required

    def test_dispatch_evaluation_schema(self):
        from app.services.supervisor.tools import DispatchEvaluationInput
        schema = DispatchEvaluationInput.model_json_schema()
        assert "work_id" in schema["properties"]
        assert "chapter_number" in schema["properties"]
        assert "chapter_content" in schema["properties"]
        required = schema.get("required", [])
        assert "work_id" in required
        assert "chapter_number" in required
        assert "chapter_content" not in required

    def test_dispatch_writing_expert_schema(self):
        from app.services.supervisor.tools import DispatchWritingExpertInput
        schema = DispatchWritingExpertInput.model_json_schema()
        assert "work_id" in schema["properties"]
        assert "problem_type" in schema["properties"]
        assert "genre_tags" in schema["properties"]
        required = schema.get("required", [])
        assert "work_id" in required
        assert "problem_type" in required
        assert "genre_tags" in required


# ────────────────────────── 3. SupervisorState 测试 ──────────────────────────


class TestSupervisorState:
    """验证 SupervisorState 定义"""

    def test_state_has_messages_field(self):
        from app.services.supervisor.state import SupervisorState
        annotations = SupervisorState.__annotations__
        assert "messages" in annotations

    def test_state_has_work_id(self):
        from app.services.supervisor.state import SupervisorState
        annotations = SupervisorState.__annotations__
        assert "work_id" in annotations

    def test_state_has_session_id(self):
        from app.services.supervisor.state import SupervisorState
        annotations = SupervisorState.__annotations__
        assert "session_id" in annotations


# ────────────────────────── 4. 查询工具单元测试 ──────────────────────────


class TestQueryToolsUnit:
    """测试查询工具的实际逻辑（mock DB）"""

    def test_query_characters_no_results(self):
        from app.services.supervisor.tools import query_characters
        mock_db = MagicMock()
        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}
        with patch("app.services.character_service.CharacterService.query_data", return_value=[]):
            result = query_characters.invoke(
                {"work_id": "w1", "filters": {}},
                config=config,
            )
        assert "没有找到" in result

    def test_query_characters_with_results(self):
        from app.services.supervisor.tools import query_characters
        mock_db = MagicMock()
        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}
        fake_chars = [
            {"name": "张三", "role_type": "男主", "gender": "男", "age": "20",
             "personality": "勇敢", "background": "", "current_status": "存活", "current_goal": "复仇"},
        ]
        with patch("app.services.character_service.CharacterService.query_data", return_value=fake_chars):
            result = query_characters.invoke(
                {"work_id": "w1", "filters": {"role_type": "男主"}},
                config=config,
            )
        assert "张三" in result
        assert "男主" in result

    def test_query_chapters_no_results(self):
        from app.services.supervisor.tools import query_chapters
        mock_db = MagicMock()
        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}
        with patch("app.services.character_service.CharacterService.query_data", return_value=[]):
            result = query_chapters.invoke(
                {"work_id": "w1", "filters": {}},
                config=config,
            )
        assert "没有找到" in result

    def test_query_chapters_with_results(self):
        from app.services.supervisor.tools import query_chapters
        mock_db = MagicMock()
        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}
        fake_chapters = [
            {"chapter_number": 1, "title": "开端", "status": "草稿", "content_preview": "在一个..."},
        ]
        with patch("app.services.character_service.CharacterService.query_data", return_value=fake_chapters):
            result = query_chapters.invoke(
                {"work_id": "w1", "filters": {"chapter_number": 1}},
                config=config,
            )
        assert "第1章" in result
        assert "开端" in result

    def test_grep_no_results(self):
        from app.services.supervisor.tools import grep
        mock_db = MagicMock()
        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}
        with patch("app.services.character_service.CharacterService.grep", return_value=[]):
            result = grep.invoke(
                {"work_id": "w1", "keyword": "不存在的内容", "scope": "all", "context_chars": 200},
                config=config,
            )
        assert "未找到" in result

    def test_grep_with_results(self):
        from app.services.supervisor.tools import grep
        mock_db = MagicMock()
        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}
        fake_results = [
            {"source": "character", "character_name": "张三", "field": "background", "snippet": "...复仇..."},
        ]
        with patch("app.services.character_service.CharacterService.grep", return_value=fake_results):
            result = grep.invoke(
                {"work_id": "w1", "keyword": "复仇", "scope": "characters", "context_chars": 200},
                config=config,
            )
        assert "张三" in result


# ────────────────────────── 5. 写作专家派发测试 ──────────────────────────


class TestWritingExpertDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_writing_expert_success(self):
        from app.services.supervisor.tools import dispatch_writing_expert

        mock_db = MagicMock()
        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}
        fake_result = {
            "options": [{"event_name": "误会升级型冲突", "how_to_use_in_this_chapter": "第8章建议..."}],
            "recommended_pick": {"event_name": "误会升级型冲突"},
            "apply_prompt_for_chapter_agent": "请改写第8章...",
        }
        with patch("app.services.supervisor.writing_expert_agent.WritingExpertAgent.advise", new=AsyncMock(return_value=fake_result)):
            result = await dispatch_writing_expert.coroutine(
                work_id="w1",
                problem_type="conflict_event",
                genre_tags=["玄幻"],
                config=config,
            )
        assert "写作专家已返回" in result
        assert "误会升级型冲突" in result


# ────────────────────────── 5. LangGraph StateGraph 构建测试 ──────────────────────────


class TestStateGraphBuild:
    """验证 StateGraph 能正确构建"""

    def test_build_graph_compiles(self):
        """StateGraph 应该能成功编译"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent
        mock_db = MagicMock()
        mock_emit = MagicMock()
        agent = SupervisorAgent(emit=mock_emit, db=mock_db, work_id="w1")
        graph = agent._build_graph()
        assert graph is not None

    def test_should_continue_with_tool_calls(self):
        """LLM 发出 tool_calls 时应路由到 tools"""
        from app.services.supervisor.supervisor_agent import _should_continue

        ai_msg = AIMessage(content="", tool_calls=[{"name": "dispatch_outline", "args": {}, "id": "tc1"}])
        state = {"messages": [ai_msg]}
        assert _should_continue(state) == "tools"

    def test_should_continue_without_tool_calls(self):
        """LLM 不调用工具时应路由到 END"""
        from app.services.supervisor.supervisor_agent import _should_continue

        ai_msg = AIMessage(content="你好！")
        state = {"messages": [ai_msg]}
        assert _should_continue(state) == "__end__"

    def test_should_continue_empty_messages(self):
        """空 messages 应路由到 END"""
        from app.services.supervisor.supervisor_agent import _should_continue
        assert _should_continue({}) == "__end__"
        assert _should_continue({"messages": []}) == "__end__"


# ────────────────────────── 6. System Prompt 测试 ──────────────────────────


class TestSystemPrompt:
    """验证 system prompt 构建"""

    def test_system_prompt_without_work(self):
        from app.services.supervisor.supervisor_agent import _build_system_message
        msg = _build_system_message(work_id=None, db=MagicMock())
        assert "未绑定作品" in msg.content
        assert "AI小说写作助手" in msg.content

    def test_system_prompt_with_work(self):
        from app.services.supervisor.supervisor_agent import _build_system_message

        mock_db = MagicMock()
        mock_work = MagicMock()
        mock_work.title = "测试小说"
        mock_work.genre = "科幻"
        mock_work.outline_tree = {"story": {"title": "测试", "genre": "科幻"}, "timeline": [{"chapter_start": 1, "chapter_end": 3}]}
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        msg = _build_system_message(work_id="w1", db=mock_db)
        assert "w1" in msg.content
        assert "测试小说" in msg.content

    def test_system_prompt_mentions_dispatch(self):
        """system prompt 应提及派发工具"""
        from app.services.supervisor.supervisor_agent import _build_system_message
        msg = _build_system_message(work_id=None, db=MagicMock())
        assert "dispatch_outline" in msg.content
        assert "dispatch_chapter" in msg.content
        assert "dispatch_evaluation" in msg.content
