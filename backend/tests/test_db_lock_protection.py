"""测试 _dispatch_outline_coroutine 中 db_lock 传递

验证：
1. 有 db_lock 时，db_lock 被传递给 OutlineAgent 的 create_outline/edit_outline
2. 无 db_lock 时不影响原有行为（向后兼容）
"""

import asyncio
import threading
import sys

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "/root/Novel/backend")


class TestDispatchOutlineDbLock:
    """验证 dispatch_outline 的 db_lock 传递"""

    @pytest.mark.asyncio
    async def test_dispatch_outline_passes_db_lock(self):
        """有 db_lock 时，应传递给 create_outline"""
        from app.services.supervisor.tools import dispatch_outline

        lock = threading.Lock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        config = {
            "configurable": {
                "db": mock_db,
                "db_lock": lock,
                "emit": lambda e, d: None,
                "supervisor_session_id": None,
            },
        }

        received_lock = None

        async def fake_create_outline(*args, **kwargs):
            nonlocal received_lock
            received_lock = kwargs.get("db_lock")
            return {"work_id": "w-new", "title": "新小说"}

        with patch(
            "app.services.supervisor.outline_agent.OutlineAgent.create_outline",
            new_callable=AsyncMock,
            side_effect=fake_create_outline,
        ):
            result = await dispatch_outline.coroutine(
                message="写一个末日科幻故事",
                work_id=None,
                config=config,
            )

        assert received_lock is lock, "db_lock 应被传递给 create_outline"

    @pytest.mark.asyncio
    async def test_dispatch_outline_no_lock_backward_compat(self):
        """无 db_lock 时，应正常工作（向后兼容）"""
        from app.services.supervisor.tools import dispatch_outline

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        config = {
            "configurable": {
                "db": mock_db,
                "emit": lambda e, d: None,
                "supervisor_session_id": None,
            },
        }

        with patch(
            "app.services.supervisor.outline_agent.OutlineAgent.create_outline",
            new_callable=AsyncMock,
            return_value={"work_id": "w-new", "title": "新小说"},
        ):
            result = await dispatch_outline.coroutine(
                message="写一个故事",
                work_id=None,
                config=config,
            )

        assert "新小说" in result or "w-new" in result

    @pytest.mark.asyncio
    async def test_dispatch_outline_edit_passes_db_lock(self):
        """编辑大纲时也应传递 db_lock"""
        from app.services.supervisor.tools import dispatch_outline

        lock = threading.Lock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        config = {
            "configurable": {
                "db": mock_db,
                "db_lock": lock,
                "emit": lambda e, d: None,
                "supervisor_session_id": None,
                "auto_mode": False,
            },
        }

        received_lock = None

        async def fake_edit_outline(*args, **kwargs):
            nonlocal received_lock
            received_lock = kwargs.get("db_lock")
            return {
                "message": "大纲变更已暂存",
                "outline_summary": {"total_added": 1, "total_modified": 0, "total_removed": 0},
                "character_summary": {"total_added": 0, "total_modified": 0, "total_removed": 0},
                "operations": [{"tool": "add_timeline_node"}],
            }

        with patch(
            "app.services.supervisor.outline_agent.OutlineAgent.edit_outline",
            new_callable=AsyncMock,
            side_effect=fake_edit_outline,
        ):
            result = await dispatch_outline.coroutine(
                message="丰富大纲",
                work_id="w-1",
                config=config,
            )

        assert received_lock is lock, "db_lock 应被传递给 edit_outline"
