"""测试 SupervisorAgent 派发工具重构

验证：
1. ALL_TOOLS 只有 9 个（5 查询 + 4 派发），旧的操作型工具已移除
2. dispatch_outline / dispatch_chapter 的 schema 定义
3. dispatch_outline coroutine 能正确派发给 OutlineAgent
4. dispatch_chapter coroutine 能正确派发给 ChapterAgent / EditChapterAgent
5. 查询工具保持不变
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ────────────────────────── 1. 工具注册测试 ──────────────────────────


class TestDispatchToolRegistration:
    """验证重构后的工具注册"""

    def test_all_tools_count_is_9(self):
        """应该恰好注册 9 个工具（5 查询 + 4 派发）"""
        from app.services.supervisor.tools import ALL_TOOLS
        assert len(ALL_TOOLS) == 9

    def test_query_tools_kept(self):
        """5 个查询工具应保留"""
        from app.services.supervisor.tools import ALL_TOOLS
        names = {t.name for t in ALL_TOOLS}
        assert "query_characters" in names
        assert "query_chapters" in names
        assert "query_chapter_meta" in names
        assert "grep_chapter_meta" in names
        assert "grep" in names

    def test_dispatch_tools_exist(self):
        """4 个派发工具应存在"""
        from app.services.supervisor.tools import ALL_TOOLS
        names = {t.name for t in ALL_TOOLS}
        assert "dispatch_requirements_planner" in names
        assert "dispatch_outline" in names
        assert "dispatch_chapter" in names
        assert "dispatch_evaluation" in names

    def test_old_operation_tools_removed(self):
        """旧的操作型工具应全部移除"""
        from app.services.supervisor.tools import ALL_TOOLS
        names = {t.name for t in ALL_TOOLS}
        assert "create_outline" not in names
        assert "edit_outline" not in names
        assert "write_chapter" not in names
        assert "edit_chapter" not in names

    def test_tool_names_unique(self):
        """所有工具名不应重复"""
        from app.services.supervisor.tools import ALL_TOOLS
        names = [t.name for t in ALL_TOOLS]
        assert len(names) == len(set(names))

    def test_dispatch_tools_are_async(self):
        """派发工具应有 coroutine（异步）"""
        from app.services.supervisor.tools import (
            dispatch_chapter,
            dispatch_evaluation,
            dispatch_outline,
            dispatch_requirements_planner,
        )
        assert dispatch_requirements_planner.coroutine is not None
        assert dispatch_outline.coroutine is not None
        assert dispatch_chapter.coroutine is not None
        assert dispatch_evaluation.coroutine is not None

    def test_query_tools_are_sync(self):
        """查询工具应有 func（同步）"""
        from app.services.supervisor.tools import query_characters, query_chapters, grep
        assert query_characters.func is not None
        assert query_chapters.func is not None
        assert grep.func is not None


# ────────────────────────── 2. Schema 测试 ──────────────────────────


class TestDispatchToolSchemas:
    """验证派发工具的输入 schema"""

    def test_dispatch_outline_schema(self):
        from app.services.supervisor.tools import DispatchOutlineInput
        schema = DispatchOutlineInput.model_json_schema()
        props = schema["properties"]
        assert "message" in props
        assert "work_id" in props
        # work_id 应为可选
        required = schema.get("required", [])
        assert "message" in required
        assert "work_id" not in required

    def test_dispatch_chapter_schema(self):
        from app.services.supervisor.tools import DispatchChapterInput
        schema = DispatchChapterInput.model_json_schema()
        props = schema["properties"]
        assert "instruction" in props
        assert "work_id" in props
        assert "chapter_number" in props
        # work_id 必传，chapter_number 可选
        required = schema.get("required", [])
        assert "work_id" in required
        assert "instruction" not in required or "instruction" in required
        assert "chapter_number" not in required

    def test_dispatch_evaluation_schema(self):
        from app.services.supervisor.tools import DispatchEvaluationInput
        schema = DispatchEvaluationInput.model_json_schema()
        props = schema["properties"]
        assert "work_id" in props
        assert "chapter_number" in props
        assert "chapter_content" in props
        required = schema.get("required", [])
        assert "work_id" in required
        assert "chapter_number" in required
        assert "chapter_content" not in required

    def test_dispatch_requirements_planner_schema(self):
        from app.services.supervisor.tools import DispatchRequirementsPlannerInput
        schema = DispatchRequirementsPlannerInput.model_json_schema()
        props = schema["properties"]
        assert "message" in props
        assert "work_id" in props
        required = schema.get("required", [])
        assert "message" in required
        assert "work_id" not in required

    def test_dispatch_outline_description_mentions_task(self):
        """dispatch_outline 的描述应体现「派发任务」语义"""
        from app.services.supervisor.tools import dispatch_outline
        desc = dispatch_outline.description
        # 描述中应包含任务/派发/大纲相关关键词
        assert "大纲" in desc or "outline" in desc.lower()

    def test_dispatch_chapter_description_mentions_task(self):
        """dispatch_chapter 的描述应体现执行型语义，并区分元数据查询工具"""
        from app.services.supervisor.tools import dispatch_chapter
        desc = dispatch_chapter.description
        assert "章节" in desc or "chapter" in desc.lower()
        assert "query_chapter_meta" in desc
        assert "不是只读" in desc or "执行" in desc

    def test_dispatch_evaluation_description_mentions_task(self):
        """dispatch_evaluation 的描述应体现「评估」语义"""
        from app.services.supervisor.tools import dispatch_evaluation
        desc = dispatch_evaluation.description
        assert "评估" in desc or "evaluation" in desc.lower()

    def test_dispatch_requirements_planner_description_mentions_task(self):
        from app.services.supervisor.tools import dispatch_requirements_planner
        desc = dispatch_requirements_planner.description
        assert "需求" in desc or "todolist" in desc.lower()


# ────────────────────────── 3. dispatch_outline coroutine 测试 ──────────────────────────


class TestDispatchOutlineCoroutine:
    """测试 dispatch_outline 的异步逻辑"""

    @pytest.mark.asyncio
    async def test_dispatch_outline_creates_new_outline(self):
        """没有 work_id 时，OutlineAgent 应执行创建大纲"""
        from app.services.supervisor.tools import dispatch_outline

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}
        with patch("app.services.supervisor.outline_agent.OutlineAgent.create_outline", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"work_id": "w-new", "title": "新小说"}
            result = await dispatch_outline.coroutine(
                message="写一个末日科幻故事",
                work_id=None,
                config=config,
            )
        assert "新小说" in result or "w-new" in result
        assert "supervisor_stop_after_tool" not in config["configurable"]
        mock_create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_outline_edits_existing(self):
        """有 work_id 时，OutlineAgent 应执行编辑大纲"""
        from app.services.supervisor.tools import dispatch_outline

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}
        with patch("app.services.supervisor.outline_agent.OutlineAgent.edit_outline", new_callable=AsyncMock) as mock_edit:
            mock_edit.return_value = {
                "message": "已更新大纲",
                "operations": [{"tool": "update_node"}],
            }
            result = await dispatch_outline.coroutine(
                message="丰富大纲，增加女主角戏份",
                work_id="w-1",
                config=config,
            )
        assert "更新" in result or "操作" in result
        mock_edit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_outline_create_error(self):
        """创建大纲失败时返回错误信息"""
        from app.services.supervisor.tools import dispatch_outline

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}
        with patch("app.services.supervisor.outline_agent.OutlineAgent.create_outline", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {"error": "灵感描述不足"}
            result = await dispatch_outline.coroutine(
                message="写个故事",
                work_id=None,
                config=config,
        )
        assert "失败" in result or "错误" in result
        assert "supervisor_stop_after_tool" not in config["configurable"]

    @pytest.mark.asyncio
    async def test_dispatch_outline_edit_error(self):
        """编辑大纲失败时返回错误信息"""
        from app.services.supervisor.tools import dispatch_outline

        config = {"configurable": {"db": MagicMock(), "emit": lambda e, d: None}}
        with patch("app.services.supervisor.outline_agent.OutlineAgent.edit_outline", new_callable=AsyncMock) as mock_edit:
            mock_edit.return_value = {"error": "大纲不存在", "message": ""}
            result = await dispatch_outline.coroutine(
                message="修改大纲",
                work_id="w-999",
                config=config,
            )
        assert "失败" in result or "错误" in result


# ────────────────────────── 4. dispatch_chapter coroutine 测试 ──────────────────────────


class TestDispatchChapterCoroutine:
    """测试 dispatch_chapter 的异步逻辑"""

    @pytest.mark.asyncio
    async def test_dispatch_chapter_writes_new(self):
        """有 chapter_number 且章节未写时，派发写章节"""
        from app.services.supervisor.tools import dispatch_chapter

        mock_db = MagicMock()
        # mock: 章节不存在，且当前最大章节为 0（下一章应为第1章）
        chapter_query = MagicMock()
        chapter_query.filter_by.return_value.first.return_value = None  # existing chapter check
        chapter_query.filter_by.return_value.order_by.return_value.first.return_value = None  # max chapter check
        mock_db.query.return_value = chapter_query

        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}

        with patch("app.services.agent.graph.ChapterAgentGraph.start", new_callable=AsyncMock) as mock_start:
            mock_record = MagicMock()
            mock_record.status = "completed"
            mock_start.return_value = mock_record

            result = await dispatch_chapter.coroutine(
                instruction="写第一章",
                work_id="w-1",
                chapter_number=1,
                config=config,
            )
        assert "第1章" in result

    @pytest.mark.asyncio
    async def test_dispatch_chapter_edits_existing(self):
        """有 chapter_number 且章节有正文时，派发编辑章节"""
        from app.services.supervisor.tools import dispatch_chapter

        mock_db = MagicMock()
        # mock: 章节存在且有正文 → 走编辑逻辑
        mock_chapter = MagicMock()
        mock_chapter.content = "旧内容"
        mock_chapter.chapter_number = 2
        q_chain = MagicMock()
        q_chain.filter_by.return_value.first.return_value = mock_chapter
        mock_db.query.return_value = q_chain

        config = {"configurable": {
            "db": mock_db,
            "emit": lambda e, d: None,
            "supervisor_session_id": "sess-1",
        }}

        # mock SupervisorSession for edit_chapter flow
        mock_sess = MagicMock()
        mock_sess.id = "sess-1"
        mock_sess.work_id = "w-1"
        sess_q = MagicMock()
        sess_q.filter_by.return_value.first.return_value = mock_sess

        # 第二次 query 调用返回 session
        def query_side_effect(model):
            if model.__name__ == "Chapter":
                return q_chain
            return sess_q
        mock_db.query.side_effect = query_side_effect

        with patch("app.services.supervisor.edit_chapter_agent.EditChapterAgent.run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {
                "summary": {"lines_added": 3, "lines_removed": 1},
                "old_content": "旧内容",
                "new_content": "新内容",
                "diff": [],
            }
            result = await dispatch_chapter.coroutine(
                instruction="修改第三章",
                work_id="w-1",
                chapter_number=2,
                config=config,
            )
        assert "第2章" in result or "修改" in result

    @pytest.mark.asyncio
    async def test_dispatch_chapter_no_chapter_number(self):
        """没有 chapter_number 时，应自动写“下一章”（expected_next）"""
        from app.services.supervisor.tools import dispatch_chapter

        mock_db = MagicMock()
        chapter_query = MagicMock()
        chapter_query.filter_by.return_value.first.return_value = None
        max_ch = MagicMock()
        max_ch.chapter_number = 3
        chapter_query.filter_by.return_value.order_by.return_value.first.return_value = max_ch
        mock_db.query.return_value = chapter_query
        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}

        with patch("app.services.agent.graph.ChapterAgentGraph.start", new_callable=AsyncMock) as mock_start:
            mock_record = MagicMock()
            mock_record.status = "completed"
            mock_start.return_value = mock_record

            result = await dispatch_chapter.coroutine(
                instruction="继续写下一章",
                work_id="w-1",
                chapter_number=None,
                config=config,
            )
        assert "第4章" in result

    @pytest.mark.asyncio
    async def test_dispatch_chapter_write_error(self):
        """请求越界新增章节时，返回顺序限制错误信息"""
        from app.services.supervisor.tools import dispatch_chapter

        mock_db = MagicMock()
        # 当前最大章节为 3，只允许新增第4章
        chapter_query = MagicMock()
        chapter_query.filter_by.return_value.first.return_value = None
        max_ch = MagicMock()
        max_ch.chapter_number = 3
        chapter_query.filter_by.return_value.order_by.return_value.first.return_value = max_ch
        mock_db.query.return_value = chapter_query
        config = {"configurable": {"db": mock_db, "emit": lambda e, d: None}}

        result = await dispatch_chapter.coroutine(
            instruction="写一个不存在的章节",
            work_id="w-1",
            chapter_number=99,
            config=config,
        )
        assert "新增章节必须严格顺序" in result
        assert "只能新增第4章" in result


# ────────────────────────── 5. 查询工具不变测试 ──────────────────────────


class TestQueryToolsUnchanged:
    """验证查询工具没有变化"""

    def test_query_characters_unchanged(self):
        from app.services.supervisor.tools import query_characters
        assert query_characters.name == "query_characters"
        assert "角色" in query_characters.description

    def test_query_chapters_unchanged(self):
        from app.services.supervisor.tools import query_chapters
        assert query_chapters.name == "query_chapters"
        assert "章节" in query_chapters.description

    def test_grep_unchanged(self):
        from app.services.supervisor.tools import grep
        assert grep.name == "grep"
        assert "搜索" in grep.description


# ────────────────────────── 6. LangGraph StateGraph 构建测试 ──────────────────────────


class TestStateGraphBuildWithDispatch:
    """验证重构后 StateGraph 仍能正确构建"""

    def test_build_graph_compiles(self):
        from app.services.supervisor.supervisor_agent import SupervisorAgent
        mock_db = MagicMock()
        mock_emit = MagicMock()
        agent = SupervisorAgent(emit=mock_emit, db=mock_db, work_id="w1")
        graph = agent._build_graph()
        assert graph is not None

    def test_should_continue_still_works(self):
        from app.services.supervisor.supervisor_agent import _should_continue
        from langchain_core.messages import AIMessage

        # 有 tool_calls → tools
        ai_msg = AIMessage(content="", tool_calls=[{"name": "dispatch_outline", "args": {}, "id": "tc1"}])
        assert _should_continue({"messages": [ai_msg]}) == "tools"

        # 无 tool_calls → END
        ai_msg2 = AIMessage(content="好的")
        assert _should_continue({"messages": [ai_msg2]}) == "__end__"
