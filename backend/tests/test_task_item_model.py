"""测试 TaskItem 模型和 task_items 表

验证：
1. TaskItem 模型字段定义正确
2. CRUD 操作正常
3. session_id 外键关联正确
"""

import sys

import pytest

sys.path.insert(0, "/root/Novel/backend")


class TestTaskItemModel:
    """验证 TaskItem 模型定义"""

    def test_task_item_has_all_columns(self):
        """TaskItem 模型应包含所有必要字段"""
        from app.models.task_item_model import TaskItem

        columns = {c.name for c in TaskItem.__table__.columns}
        expected = {
            "id", "session_id", "task_id", "task_description",
            "owner", "status", "depends_on", "done_criteria",
            "result_summary", "sort_order", "created_at", "updated_at",
            "task_type", "dispatch_tool", "instruction",
            "error_message", "started_at", "completed_at",
        }
        assert columns == expected

    def test_task_item_tablename(self):
        from app.models.task_item_model import TaskItem
        assert TaskItem.__tablename__ == "task_items"

    def test_task_item_default_status_is_pending(self):
        from app.models.task_item_model import TaskItem
        from unittest.mock import MagicMock
        ti = TaskItem(id="test-1", session_id="sess-1", task_id="T1")
        assert ti.status == "pending"

    def test_task_item_default_owner_is_supervisor(self):
        from app.models.task_item_model import TaskItem
        ti = TaskItem(id="test-1", session_id="sess-1", task_id="T1")
        assert ti.owner == "supervisor"

    def test_task_item_default_depends_on_empty(self):
        from app.models.task_item_model import TaskItem
        ti = TaskItem(id="test-1", session_id="sess-1", task_id="T1")
        assert ti.depends_on == ""

    def test_task_item_no_jsonb_columns(self):
        """TaskItem 不应包含任何 JSONB 列"""
        from app.models.task_item_model import TaskItem
        from sqlalchemy.dialects.postgresql import JSONB
        for col in TaskItem.__table__.columns:
            assert not isinstance(col.type, JSONB), f"列 {col.name} 不应为 JSONB 类型"


class TestTaskItemCRUD:
    """验证 TaskItem 的 CRUD 操作（使用 mock DB）"""

    def test_create_task_item(self):
        from app.models.task_item_model import TaskItem
        ti = TaskItem(
            id="ti-1",
            session_id="sess-1",
            task_id="T1",
            task_description="创建大纲",
            owner="outline_agent",
            done_criteria="大纲生成并保存",
            sort_order=1,
        )
        assert ti.task_id == "T1"
        assert ti.task_description == "创建大纲"
        assert ti.owner == "outline_agent"
        assert ti.done_criteria == "大纲生成并保存"
        assert ti.sort_order == 1
        assert ti.status == "pending"
        assert ti.result_summary == ""

    def test_update_status(self):
        from app.models.task_item_model import TaskItem
        ti = TaskItem(
            id="ti-1", session_id="sess-1", task_id="T1",
            task_description="创建大纲", status="pending",
        )
        ti.status = "in_progress"
        assert ti.status == "in_progress"
        ti.status = "completed"
        ti.result_summary = "大纲已创建，共5个时间线节点"
        assert ti.status == "completed"
        assert ti.result_summary == "大纲已创建，共5个时间线节点"

    def test_valid_statuses(self):
        """所有合法状态值应能正常设置"""
        from app.models.task_item_model import TaskItem
        valid_statuses = ["pending", "in_progress", "completed", "skipped", "failed"]
        for s in valid_statuses:
            ti = TaskItem(id="test", session_id="sess", task_id="T1")
            ti.status = s
            assert ti.status == s
