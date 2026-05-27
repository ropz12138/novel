"""测试合并后的 ChapterAgent

验证：
1. 工具集合并（去重）正确
2. ChapterAgentState 状态定义
3. LangGraph StateGraph 构建与编译
4. 系统提示词模板渲染
5. ChapterAgent.run 新写 / 编辑模式
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


# ────────────────────────── 1. 工具集合并测试 ──────────────────────────


class TestChapterAgentToolRegistration:
    """验证合并后的工具集"""

    def test_chapter_agent_tools_no_duplicates(self):
        from app.services.supervisor.chapter_agent import CHAPTER_AGENT_TOOLS
        names = [t.name for t in CHAPTER_AGENT_TOOLS]
        assert len(names) == len(set(names)), f"Duplicate tool names: {names}"

    def test_chapter_agent_tools_contains_write_tools(self):
        from app.services.supervisor.chapter_agent import CHAPTER_AGENT_TOOLS
        names = {t.name for t in CHAPTER_AGENT_TOOLS}
        write_tools = {
            "query_outline",
            "query_chapter_outline",
            "query_previous_chapters",
            "query_characters",
            "query_foreshadowing",
            "generate_chapter_content",
            "save_chapter",
            "update_characters_after_chapter",
        }
        assert write_tools.issubset(names), f"Missing write tools: {write_tools - names}"

    def test_chapter_agent_tools_contains_edit_tools(self):
        from app.services.supervisor.chapter_agent import CHAPTER_AGENT_TOOLS
        names = {t.name for t in CHAPTER_AGENT_TOOLS}
        edit_tools = {
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
        assert edit_tools.issubset(names), f"Missing edit tools: {edit_tools - names}"

    def test_chapter_agent_tools_contains_shared_tools(self):
        from app.services.supervisor.chapter_agent import CHAPTER_AGENT_TOOLS
        names = {t.name for t in CHAPTER_AGENT_TOOLS}
        shared_tools = {
            "create_child_todolist",
            "read_child_todolist",
            "update_child_task_status",
        }
        assert shared_tools.issubset(names), f"Missing shared tools: {shared_tools - names}"


# ────────────────────────── 2. 状态定义测试 ──────────────────────────


class TestChapterAgentState:
    """验证合并后的 ChapterAgentState"""

    def test_state_has_messages(self):
        from app.services.supervisor.chapter_agent import ChapterAgentState
        annotations = ChapterAgentState.__annotations__
        assert "messages" in annotations

    def test_state_has_work_id(self):
        from app.services.supervisor.chapter_agent import ChapterAgentState
        annotations = ChapterAgentState.__annotations__
        assert "work_id" in annotations

    def test_state_has_chapter_number(self):
        from app.services.supervisor.chapter_agent import ChapterAgentState
        annotations = ChapterAgentState.__annotations__
        assert "chapter_number" in annotations

    def test_state_has_user_message(self):
        from app.services.supervisor.chapter_agent import ChapterAgentState
        annotations = ChapterAgentState.__annotations__
        assert "user_message" in annotations

    def test_state_has_auto_mode(self):
        from app.services.supervisor.chapter_agent import ChapterAgentState
        annotations = ChapterAgentState.__annotations__
        assert "auto_mode" in annotations


# ────────────────────────── 3. LangGraph 构建测试 ──────────────────────────


class TestChapterAgentGraphBuild:
    """验证 ChapterAgent 的 LangGraph 构建"""

    def test_build_graph_compiles(self):
        from app.services.supervisor.chapter_agent import ChapterAgent
        mock_emit = MagicMock()
        agent = ChapterAgent(emit=mock_emit)
        graph = agent._build_graph()
        assert graph is not None


# ────────────────────────── 4. 系统提示词测试 ──────────────────────────


class TestSystemPrompt:
    """验证系统提示词模板渲染"""

    def test_new_chapter_prompt(self):
        from app.services.supervisor.chapter_agent import _build_system_prompt
        prompt = _build_system_prompt(
            work_id="w1",
            chapter_number=3,
            user_message="写第三章",
            is_new_chapter=True,
            auto_mode=True,
        )
        assert "第3章" in prompt
        assert "撰写新章节" in prompt
        assert "自动模式" in prompt
        assert "写第三章" in prompt

    def test_edit_chapter_prompt(self):
        from app.services.supervisor.chapter_agent import _build_system_prompt
        prompt = _build_system_prompt(
            work_id="w1",
            chapter_number=2,
            user_message="修改结尾",
            is_new_chapter=False,
            auto_mode=False,
        )
        assert "第2章" in prompt
        assert "编辑已有章节" in prompt
        assert "交互模式" in prompt
        assert "修改结尾" in prompt

    def test_prompt_forbids_chapter_number_rewrite(self):
        from app.services.supervisor.chapter_agent import _build_system_prompt
        prompt = _build_system_prompt(
            work_id="w1",
            chapter_number=2,
            user_message="写第二章",
            is_new_chapter=True,
            auto_mode=True,
        )
        assert "不得因为该章已存在而自行改写为第3章" in prompt
        assert "不得创建其他章节" in prompt

    def test_prompt_mentions_all_tools(self):
        from app.services.supervisor.chapter_agent import _build_system_prompt
        prompt = _build_system_prompt(
            work_id="w1",
            chapter_number=1,
            user_message="test",
            is_new_chapter=True,
            auto_mode=True,
        )
        assert "generate_chapter_content" in prompt
        assert "generate_patch_edit" in prompt
        assert "rewrite_chapter" in prompt
        assert "read_chapter" in prompt
        assert "update_characters_after_chapter" in prompt
        assert "sync_chapter_metadata" in prompt

    def test_prompt_without_fixed_chapter_number(self):
        from app.services.supervisor.chapter_agent import _build_system_prompt
        prompt = _build_system_prompt(
            work_id="w1",
            chapter_number=None,
            user_message="写第九章，承接第8章结尾",
            is_new_chapter=None,
            auto_mode=True,
        )
        assert "目标章节：未由系统固定" in prompt
        assert "显式传入 chapter_number" in prompt
        assert "不要依赖系统从自然语言中解析章节号" in prompt


# ────────────────────────── 5. 条件边测试 ──────────────────────────


class TestShouldContinue:
    """验证条件边逻辑"""

    def test_should_continue_with_tool_calls(self):
        from app.services.supervisor.chapter_agent import _should_continue
        from langgraph.graph import END

        mock_msg = MagicMock()
        mock_msg.tool_calls = [{"name": "some_tool"}]
        state = {"messages": [mock_msg]}
        assert _should_continue(state) == "tools"

    def test_should_continue_without_tool_calls(self):
        from app.services.supervisor.chapter_agent import _should_continue
        from langgraph.graph import END

        mock_msg = MagicMock(spec=AIMessage)
        mock_msg.content = "完成"
        state = {"messages": [mock_msg]}
        assert _should_continue(state) == END

    def test_should_continue_empty_messages(self):
        from app.services.supervisor.chapter_agent import _should_continue
        from langgraph.graph import END

        state = {"messages": []}
        assert _should_continue(state) == END


# ────────────────────────── 6. 辅助函数测试 ──────────────────────────


class TestHelperFunctions:
    """验证辅助函数"""

    def test_extract_content_from_read(self):
        from app.services.supervisor.chapter_agent import _extract_content_from_read
        text = "前面内容\n--- 正文开始 ---\n实际正文\n--- 正文结束 ---\n后面内容"
        result = _extract_content_from_read(text)
        assert result == "实际正文"

    def test_extract_content_from_read_no_markers(self):
        from app.services.supervisor.chapter_agent import _extract_content_from_read
        text = "没有标记的文本"
        result = _extract_content_from_read(text)
        assert result == ""

    def test_build_diff(self):
        from app.services.supervisor.chapter_agent import _build_diff
        old = "第一行\n第二行\n"
        new = "第一行\n修改行\n"
        diff = _build_diff(old, new)
        types = [d["type"] for d in diff]
        assert "context" in types
        assert "removed" in types or "added" in types

    def test_summarize_diff(self):
        from app.services.supervisor.chapter_agent import _summarize_diff
        diff = [
            {"type": "added", "line": "新行"},
            {"type": "removed", "line": "旧行"},
            {"type": "context", "line": "相同行"},
        ]
        summary = _summarize_diff(diff)
        assert summary["lines_added"] == 1
        assert summary["lines_removed"] == 1
        assert summary["total_changes"] == 2


# ────────────────────────── 7. run 方法测试 ──────────────────────────


class TestChapterAgentRun:
    """验证 ChapterAgent.run 的基本流程"""

    @pytest.mark.asyncio
    async def test_run_new_chapter_emits_stage_start(self):
        from app.services.supervisor.chapter_agent import ChapterAgent

        emitted = []
        emit = lambda event, data=None: emitted.append((event, data))

        agent = ChapterAgent(emit=emit)
        mock_db = MagicMock()

        with patch.object(agent, '_build_graph') as mock_build:
            mock_graph = MagicMock()

            async def fake_astream(*args, **kwargs):
                yield {"agent": {"messages": [AIMessage(content="写作完成")]}}

            mock_graph.astream = fake_astream
            mock_build.return_value = mock_graph

            result = await agent.run(
                work_id="w1",
                chapter_number=1,
                user_message="写第一章",
                db=mock_db,
                is_new_chapter=True,
                auto_mode=True,
            )

        assert result["message"] == "写作完成"
        stage_events = [e for e in emitted if e[0] == "stage_start"]
        assert len(stage_events) == 1
        assert stage_events[0][1]["stage"] == "chapter_agent"
        assert "写第1章" in stage_events[0][1]["label"]

    @pytest.mark.asyncio
    async def test_run_edit_chapter_emits_correct_label(self):
        from app.services.supervisor.chapter_agent import ChapterAgent

        emitted = []
        emit = lambda event, data=None: emitted.append((event, data))

        agent = ChapterAgent(emit=emit)
        mock_db = MagicMock()

        with patch.object(agent, '_build_graph') as mock_build:
            mock_graph = MagicMock()

            async def fake_astream(*args, **kwargs):
                yield {"agent": {"messages": [AIMessage(content="编辑完成")]}}

            mock_graph.astream = fake_astream
            mock_build.return_value = mock_graph

            result = await agent.run(
                work_id="w1",
                chapter_number=2,
                user_message="修改结尾",
                db=mock_db,
                is_new_chapter=False,
                auto_mode=True,
            )

        stage_events = [e for e in emitted if e[0] == "stage_start"]
        assert len(stage_events) == 1
        assert "处理第2章" in stage_events[0][1]["label"]

    @pytest.mark.asyncio
    async def test_run_edit_generates_diff(self):
        from app.services.supervisor.chapter_agent import ChapterAgent

        emitted = []
        emit = lambda event, data=None: emitted.append((event, data))

        agent = ChapterAgent(emit=emit)
        mock_db = MagicMock()

        mock_chapter = MagicMock()
        mock_chapter.content = "旧正文\n修改行\n"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_chapter

        tool_msg = MagicMock()
        tool_msg.name = "read_chapter"
        tool_msg.content = "--- 正文开始 ---\n旧正文\n旧行\n--- 正文结束 ---"

        with patch.object(agent, '_build_graph') as mock_build:
            mock_graph = MagicMock()

            async def fake_astream(*args, **kwargs):
                yield {
                    "agent": {
                        "messages": [
                            tool_msg,
                            AIMessage(content="编辑完成"),
                        ]
                    }
                }

            mock_graph.astream = fake_astream
            mock_build.return_value = mock_graph

            result = await agent.run(
                work_id="w1",
                chapter_number=1,
                user_message="修改第二行",
                db=mock_db,
                is_new_chapter=False,
                auto_mode=True,
                emit_diff_event=True,
            )

        assert "diff" in result
        assert "old_content" in result
        assert "new_content" in result
        diff_events = [e for e in emitted if e[0] == "edit_chapter_diff"]
        assert len(diff_events) == 1

    @pytest.mark.asyncio
    async def test_run_without_fixed_chapter_number_emits_generic_label(self):
        from app.services.supervisor.chapter_agent import ChapterAgent

        emitted = []
        emit = lambda event, data=None: emitted.append((event, data))

        agent = ChapterAgent(emit=emit)
        mock_db = MagicMock()

        with patch.object(agent, '_build_graph') as mock_build:
            mock_graph = MagicMock()

            async def fake_astream(*args, **kwargs):
                yield {"agent": {"messages": [AIMessage(content="章节任务完成")]}}

            mock_graph.astream = fake_astream
            mock_build.return_value = mock_graph

            result = await agent.run(
                work_id="w1",
                user_message="写第九章，承接第8章结尾",
                db=mock_db,
                chapter_number=None,
                is_new_chapter=None,
                auto_mode=True,
            )

        assert result["message"] == "章节任务完成"
        stage_events = [e for e in emitted if e[0] == "stage_start"]
        assert len(stage_events) == 1
        assert stage_events[0][1]["label"] == "处理章节任务"

    @pytest.mark.asyncio
    async def test_run_ignores_bool_node_output_in_astream(self):
        """LangGraph 流式事件末尾可能带 bool 节点输出，不应导致 final_state.get 崩溃。"""
        from app.services.supervisor.chapter_agent import ChapterAgent

        agent = ChapterAgent(emit=lambda event, data=None: None)
        mock_db = MagicMock()

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = MagicMock()

            async def fake_astream(*args, **kwargs):
                yield {"agent": {"messages": [AIMessage(content="第10章写作完成")]}}
                yield {"__pregel_checkpointer": True}

            mock_graph.astream = fake_astream
            mock_build.return_value = mock_graph

            result = await agent.run(
                work_id="w1",
                user_message="写第10章",
                db=mock_db,
                chapter_number=None,
                is_new_chapter=None,
                auto_mode=True,
            )

        assert result["message"] == "第10章写作完成"


# ────────────────────────── 8. accept_edit 测试 ──────────────────────────


class TestAcceptEdit:
    """验证 accept_edit 方法"""

    def test_accept_edit_success(self):
        from app.services.supervisor.chapter_agent import ChapterAgent

        emitted = []
        emit = lambda event, data=None: emitted.append((event, data))

        agent = ChapterAgent(emit=emit)
        mock_db = MagicMock()
        mock_chapter = MagicMock()
        mock_chapter.title = "第一章"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_chapter

        result = agent.accept_edit(
            work_id="w1",
            chapter_number=1,
            new_content="新正文内容",
            db=mock_db,
        )

        assert result["success"] is True
        assert result["title"] == "第一章"
        mock_db.commit.assert_called()

    def test_accept_edit_chapter_not_found(self):
        from app.services.supervisor.chapter_agent import ChapterAgent

        emitted = []
        emit = lambda event, data=None: emitted.append((event, data))

        agent = ChapterAgent(emit=emit)
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        result = agent.accept_edit(
            work_id="w1",
            chapter_number=99,
            new_content="内容",
            db=mock_db,
        )

        assert "error" in result
