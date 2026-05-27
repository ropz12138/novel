"""测试 configurable 中 work_id 的注入与回退

验证：
1. _run_graph 构建的 config.configurable 中包含 work_id
2. 从子 Agent 引入的工具（read_outline、read_chapter）能从 configurable 获取 work_id
3. 当 session.work_id 为空时（创建新大纲场景），work_id 应为空字符串而非 None
4. _get_work_id 在 configurable 中没有 work_id 时，能从 session 回退获取
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.runnables import RunnableConfig


# ────────────────────────── 1. configurable 注入测试 ──────────────────────────


class TestConfigurableWorkIdInjection:
    """验证 _run_graph 在 config.configurable 中注入 work_id"""

    @pytest.mark.asyncio
    async def test_run_graph_injects_work_id_from_session(self):
        """session.work_id 应被注入到 configurable.work_id"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        mock_db = MagicMock()
        mock_emit = MagicMock()
        agent = SupervisorAgent(emit=mock_emit, db=mock_db, work_id="w-test-123")

        mock_session = MagicMock()
        mock_session.id = "test-session"
        mock_session.auto_mode = True
        mock_session.work_id = "w-test-123"
        mock_session.status = "running"

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = AsyncMock()
            mock_graph.astream.return_value = AsyncIterator([])
            mock_build.return_value = mock_graph

            with patch("app.services.supervisor.supervisor_agent.message_service") as mock_msg:
                mock_msg.get_messages_by_session.return_value = []

                await agent._run_graph(mock_session, "test message")

        call_args = mock_graph.astream.call_args
        config = call_args[1]["config"]
        assert config["configurable"].get("work_id") == "w-test-123"

    @pytest.mark.asyncio
    async def test_run_graph_work_id_empty_when_no_session_work(self):
        """当 session.work_id 为 None 时（如创建新大纲场景），work_id 应为空字符串"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        mock_db = MagicMock()
        mock_emit = MagicMock()
        agent = SupervisorAgent(emit=mock_emit, db=mock_db, work_id=None)

        mock_session = MagicMock()
        mock_session.id = "test-session"
        mock_session.auto_mode = True
        mock_session.work_id = None
        mock_session.status = "running"

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = AsyncMock()
            mock_graph.astream.return_value = AsyncIterator([])
            mock_build.return_value = mock_graph

            with patch("app.services.supervisor.supervisor_agent.message_service") as mock_msg:
                mock_msg.get_messages_by_session.return_value = []

                await agent._run_graph(mock_session, "创建一个新故事")

        call_args = mock_graph.astream.call_args
        config = call_args[1]["config"]
        assert config["configurable"].get("work_id") == ""

    @pytest.mark.asyncio
    async def test_run_graph_work_id_from_session_overrides_agent(self):
        """如果 session.work_id 与 agent.work_id 不同，应使用 session.work_id（resume 场景）"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        mock_db = MagicMock()
        mock_emit = MagicMock()
        agent = SupervisorAgent(emit=mock_emit, db=mock_db, work_id="w-old")

        mock_session = MagicMock()
        mock_session.id = "test-session"
        mock_session.auto_mode = True
        mock_session.work_id = "w-new"
        mock_session.status = "running"

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = AsyncMock()
            mock_graph.astream.return_value = AsyncIterator([])
            mock_build.return_value = mock_graph

            with patch("app.services.supervisor.supervisor_agent.message_service") as mock_msg:
                mock_msg.get_messages_by_session.return_value = []

                await agent._run_graph(mock_session, "继续写")

        call_args = mock_graph.astream.call_args
        config = call_args[1]["config"]
        assert config["configurable"].get("work_id") == "w-new"


# ────────────────────────── 2. 子工具获取 work_id 测试 ──────────────────────────


class TestSubToolsGetWorkIdFromConfigurable:
    """验证从子 Agent 引入的工具能从 configurable 获取 work_id，不报错"""

    def test_read_outline_gets_work_id_from_configurable(self):
        """read_outline 应从 configurable.work_id 获取 work_id"""
        from app.services.supervisor.outline_tools import read_outline

        mock_db = MagicMock()
        mock_work = MagicMock()
        mock_work.outline_tree = {"story": {"title": "测试作品", "genre": "玄幻"}, "timeline": []}
        mock_work.title = "测试作品"
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {"configurable": {"db": mock_db, "work_id": "w1"}}
        result = read_outline.invoke({}, config=config)
        assert "测试作品" in result

    def test_read_chapter_gets_work_id_from_configurable(self):
        """read_chapter 应从 configurable.work_id 获取 work_id"""
        from app.services.supervisor.edit_chapter_tools import read_chapter

        mock_db = MagicMock()
        mock_chapter = MagicMock()
        mock_chapter.chapter_number = 1
        mock_chapter.title = "血月"
        mock_chapter.content = "正文内容"
        mock_db.query.return_value.filter_by.return_value \
            .filter.return_value.filter.return_value \
            .order_by.return_value.all.return_value = [mock_chapter]

        config = {"configurable": {"db": mock_db, "work_id": "w1"}}
        result = read_chapter.invoke({"chapter_number": 1}, config=config)
        assert "血月" in result

    def test_read_outline_raises_when_no_work_id(self):
        """read_outline 在 configurable 中没有 work_id 且 session 也没有时应报错"""
        from app.services.supervisor.outline_tools import read_outline

        mock_db = MagicMock()
        # session 也不存在 → 无法回退
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        config = {"configurable": {"db": mock_db}}
        with pytest.raises(ValueError, match="work_id"):
            read_outline.invoke({}, config=config)

    def test_read_chapter_raises_when_no_work_id(self):
        """read_chapter 在 configurable 中没有 work_id 且 session 也没有时应报错"""
        from app.services.supervisor.edit_chapter_tools import read_chapter

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        config = {"configurable": {"db": mock_db}}
        with pytest.raises(ValueError, match="work_id"):
            read_chapter.invoke({"chapter_number": 1}, config=config)


# ────────────────────────── 3. _get_work_id session 回退测试 ──────────────────────────


class TestGetWorkIdSessionFallback:
    """验证 _get_work_id 在 configurable 中没有 work_id 时能从 session 回退"""

    def _make_config_with_session(self, session_work_id: str) -> dict:
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = session_work_id
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        return {"configurable": {"db": mock_db, "supervisor_session_id": "sess-1"}}

    def test_outline_tools_fallback_to_session(self):
        from app.services.supervisor.outline_tools import _get_work_id
        config = self._make_config_with_session("w-from-session")
        assert _get_work_id(config) == "w-from-session"

    def test_edit_chapter_tools_fallback_to_session(self):
        from app.services.supervisor.edit_chapter_tools import _get_work_id
        config = self._make_config_with_session("w-from-session")
        assert _get_work_id(config) == "w-from-session"

    def test_evaluation_tools_fallback_to_session(self):
        from app.services.supervisor.evaluation_tools import _get_work_id
        config = self._make_config_with_session("w-from-session")
        assert _get_work_id(config) == "w-from-session"

    def test_chapter_tools_fallback_to_session(self):
        from app.services.agent.chapter_tools import _get_work_id
        config = self._make_config_with_session("w-from-session")
        assert _get_work_id(config) == "w-from-session"

    def test_no_work_id_and_no_session_raises(self):
        """configurable 没有 work_id 且没有 session_id 时应报错"""
        from app.services.supervisor.outline_tools import _get_work_id
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        config = {"configurable": {"db": mock_db}}
        with pytest.raises(ValueError, match="work_id"):
            _get_work_id(config)

    def test_configurable_work_id_takes_priority(self):
        """configurable 中的 work_id 应优先于 session 回退"""
        from app.services.supervisor.outline_tools import _get_work_id
        mock_db = MagicMock()
        config = {"configurable": {"db": mock_db, "work_id": "w-direct"}}
        assert _get_work_id(config) == "w-direct"
        mock_db.query.assert_not_called()

    def test_session_work_id_empty_raises(self):
        """session 存在但 work_id 为空时应报错"""
        from app.services.supervisor.outline_tools import _get_work_id
        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.work_id = None
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_session
        config = {"configurable": {"db": mock_db, "supervisor_session_id": "sess-1"}}
        with pytest.raises(ValueError, match="work_id"):
            _get_work_id(config)


# ────────────────────────── 辅助类 ──────────────────────────


class AsyncIterator:
    """把同步 iterable 包装为异步迭代器"""

    def __init__(self, items):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration
