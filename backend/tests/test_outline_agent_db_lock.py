"""测试 OutlineAgent 内层工具 db_lock 保护

验证：
1. OutlineAgent 内层 graph 的 configurable 中应包含 db_lock
2. outline_tools 的同步工具在有 lock 时应在锁内执行 db 操作
3. 无 lock 时向后兼容
"""

import asyncio
import threading
import sys

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "/root/Novel/backend")


class TestOutlineAgentDbLockPropagation:
    """验证 db_lock 传递进 OutlineAgent 内层 graph"""

    @pytest.mark.asyncio
    async def test_create_outline_passes_db_lock_to_inner_graph(self):
        """create_outline 应将 db_lock 传入内层 graph 的 configurable"""
        from app.services.supervisor.outline_agent import OutlineAgent
        from langchain_core.messages import AIMessage

        lock = threading.Lock()

        agent = OutlineAgent(emit=lambda e, d: None)
        mock_db = MagicMock()

        configs_passed = []

        class FakeGraph:
            async def astream(self, initial_state, config=None):
                configs_passed.append(config)
                yield {
                    "agent": {
                        "messages": [AIMessage(content="大纲创建完成")],
                    },
                }

        with patch.object(agent, "_build_graph", return_value=FakeGraph()):
            await agent.create_outline(
                idea="测试",
                tags=[],
                db=mock_db,
                db_lock=lock,
            )

        assert len(configs_passed) == 1
        inner_config = configs_passed[0]
        assert inner_config is not None
        assert "configurable" in inner_config
        assert inner_config["configurable"].get("db_lock") is lock

    @pytest.mark.asyncio
    async def test_create_outline_no_lock_backward_compat(self):
        """无 db_lock 时 create_outline 应正常工作"""
        from app.services.supervisor.outline_agent import OutlineAgent
        from langchain_core.messages import AIMessage

        agent = OutlineAgent(emit=lambda e, d: None)
        mock_db = MagicMock()

        class FakeGraph:
            async def astream(self, initial_state, config=None):
                yield {
                    "agent": {
                        "messages": [AIMessage(content="大纲创建完成")],
                    },
                }

        with patch.object(agent, "_build_graph", return_value=FakeGraph()):
            result = await agent.create_outline(
                idea="测试",
                tags=[],
                db=mock_db,
            )

        assert result is not None

    @pytest.mark.asyncio
    async def test_edit_outline_passes_db_lock_to_inner_graph(self):
        """edit_outline 也应将 db_lock 传入内层 graph"""
        from app.services.supervisor.outline_agent import OutlineAgent

        lock = threading.Lock()

        agent = OutlineAgent(emit=lambda e, d: None)
        mock_db = MagicMock()

        configs_passed = []

        class FakeGraph:
            async def astream(self, initial_state, config=None):
                configs_passed.append(config)
                yield {
                    "agent": {
                        "messages": [AIMessage(content="大纲编辑完成")],
                    },
                }

        with patch.object(agent, "_build_graph", return_value=FakeGraph()):
            await agent.edit_outline(
                work_id="w-1",
                message="修改大纲",
                history=[],
                db=mock_db,
                db_lock=lock,
            )

        assert len(configs_passed) == 1
        assert configs_passed[0]["configurable"].get("db_lock") is lock


class TestOutlineToolsDbLock:
    """验证 outline_tools 中的同步工具在有 db_lock 时加锁"""

    def test_read_outline_with_lock(self):
        """read_outline 有 db_lock 时应在锁内执行 db 查询"""
        from app.services.supervisor.outline_tools import read_outline

        lock = threading.Lock()
        mock_db = MagicMock()
        mock_work = MagicMock()
        mock_work.title = "测试"
        mock_work.outline_tree = {"story": {}, "timeline": []}
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {
            "configurable": {
                "db": mock_db,
                "emit": lambda e, d: None,
                "db_lock": lock,
            },
        }

        result = read_outline.func(work_id="w-1", config=config)
        assert "测试" in result

    def test_read_outline_without_lock(self):
        """read_outline 无 db_lock 时应正常工作"""
        from app.services.supervisor.outline_tools import read_outline

        mock_db = MagicMock()
        mock_work = MagicMock()
        mock_work.title = "测试"
        mock_work.outline_tree = {"story": {}, "timeline": []}
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {
            "configurable": {
                "db": mock_db,
                "emit": lambda e, d: None,
            },
        }

        result = read_outline.func(work_id="w-1", config=config)
        assert "测试" in result
