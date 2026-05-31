"""测试「用户需求文档」功能

验证：
1. works 表新增 requirements_doc 字段
2. read_requirements_doc 工具：全量返回需求文档，禁止截断
3. update_requirements_doc 工具：全量覆盖写入需求文档
4. 工具注册：read 在所有 agent 可用，update 仅 supervisor 可用
5. System Prompt 注入需求文档内容
"""

import sys

import pytest

sys.path.insert(0, "/root/Novel/backend")


# ── 工具注册验证 ──


class TestRequirementsDocToolsRegistration:
    """验证需求文档工具的注册情况"""

    def test_read_requirements_doc_in_supervisor_tools(self):
        """read_requirements_doc 应注册在 supervisor ALL_TOOLS 中"""
        from app.services.supervisor.tools import ALL_TOOLS
        names = {t.name for t in ALL_TOOLS}
        assert "read_requirements_doc" in names

    def test_update_requirements_doc_in_supervisor_tools(self):
        """update_requirements_doc 应注册在 supervisor ALL_TOOLS 中"""
        from app.services.supervisor.tools import ALL_TOOLS
        names = {t.name for t in ALL_TOOLS}
        assert "update_requirements_doc" in names

    def test_read_requirements_doc_in_chapter_agent_tools(self):
        """read_requirements_doc 应注册在 ChapterAgent 工具集中"""
        from app.services.supervisor.chapter_agent import CHAPTER_AGENT_TOOLS
        names = {t.name for t in CHAPTER_AGENT_TOOLS}
        assert "read_requirements_doc" in names

    def test_update_requirements_doc_not_in_chapter_agent_tools(self):
        """update_requirements_doc 不应注册在 ChapterAgent 工具集中"""
        from app.services.supervisor.chapter_agent import CHAPTER_AGENT_TOOLS
        names = {t.name for t in CHAPTER_AGENT_TOOLS}
        assert "update_requirements_doc" not in names

    def test_read_requirements_doc_in_outline_agent_tools(self):
        """read_requirements_doc 应注册在 OutlineAgent 工具集中"""
        from app.services.supervisor.outline_tools import build_outline_tools
        tools = build_outline_tools(auto_mode=True)
        names = {t.name for t in tools}
        assert "read_requirements_doc" in names

    def test_update_requirements_doc_not_in_outline_agent_tools(self):
        """update_requirements_doc 不应注册在 OutlineAgent 工具集中"""
        from app.services.supervisor.outline_tools import build_outline_tools
        tools = build_outline_tools(auto_mode=True)
        names = {t.name for t in tools}
        assert "update_requirements_doc" not in names

    def test_read_requirements_doc_is_sync(self):
        """read_requirements_doc 应为同步工具"""
        from app.services.supervisor.tools import read_requirements_doc
        assert read_requirements_doc.func is not None

    def test_update_requirements_doc_is_sync(self):
        """update_requirements_doc 应为同步工具"""
        from app.services.supervisor.tools import update_requirements_doc
        assert update_requirements_doc.func is not None


# ── read_requirements_doc 工具行为 ──


class TestReadRequirementsDoc:
    """验证 read_requirements_doc 工具行为"""

    def test_returns_full_content_no_truncation(self):
        """应全量返回需求文档内容，禁止截断"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import read_requirements_doc

        long_content = "A" * 10000  # 1万字符
        mock_work = MagicMock()
        mock_work.requirements_doc = long_content

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {"configurable": {"db": mock_db, "work_id": "w-1"}}

        result = read_requirements_doc.func(config=config)
        assert result == long_content
        assert len(result) == 10000

    def test_returns_empty_doc_message(self):
        """无需求文档时应返回提示信息"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import read_requirements_doc

        mock_work = MagicMock()
        mock_work.requirements_doc = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {"configurable": {"db": mock_db, "work_id": "w-1"}}

        result = read_requirements_doc.func(config=config)
        assert "暂无" in result

    def test_returns_error_when_work_not_found(self):
        """作品不存在时应返回错误信息"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import read_requirements_doc

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        config = {"configurable": {"db": mock_db, "work_id": "nonexistent"}}

        result = read_requirements_doc.func(config=config)
        assert "不存在" in result

    def test_returns_error_when_no_work_id(self):
        """未绑定作品时应返回错误信息"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import read_requirements_doc

        mock_db = MagicMock()

        config = {"configurable": {"db": mock_db, "work_id": ""}}

        result = read_requirements_doc.func(config=config)
        assert "未绑定" in result or "不存在" in result


# ── update_requirements_doc 工具行为 ──


class TestUpdateRequirementsDoc:
    """验证 update_requirements_doc 工具行为"""

    def test_overwrites_content(self):
        """应全量覆盖写入需求文档"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_requirements_doc

        mock_work = MagicMock()
        mock_work.requirements_doc = "旧内容"

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        config = {"configurable": {"db": mock_db, "work_id": "w-1", "emit": lambda e, d: None}}

        new_content = "全新的需求文档内容"
        result = update_requirements_doc.func(content=new_content, config=config)

        assert mock_work.requirements_doc == new_content
        mock_db.commit.assert_called()

    def test_returns_success_message(self):
        """更新成功应返回成功信息"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_requirements_doc

        mock_work = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        emitted = []
        config = {"configurable": {"db": mock_db, "work_id": "w-1", "emit": lambda e, d: emitted.append((e, d))}}

        result = update_requirements_doc.func(content="新内容", config=config)
        assert "已更新" in result or "成功" in result

    def test_emits_event_on_update(self):
        """更新成功后应 emit requirements_doc_updated 事件"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_requirements_doc

        mock_work = MagicMock()
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = mock_work

        emitted = []
        config = {"configurable": {"db": mock_db, "work_id": "w-1", "emit": lambda e, d: emitted.append((e, d))}}

        update_requirements_doc.func(content="新内容", config=config)

        assert any(e[0] == "requirements_doc_updated" for e in emitted)

    def test_returns_error_when_work_not_found(self):
        """作品不存在时应返回错误信息"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_requirements_doc

        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None

        config = {"configurable": {"db": mock_db, "work_id": "nonexistent", "emit": lambda e, d: None}}

        result = update_requirements_doc.func(content="新内容", config=config)
        assert "不存在" in result

    def test_returns_error_when_no_work_id(self):
        """未绑定作品时应返回错误信息"""
        from unittest.mock import MagicMock
        from app.services.supervisor.tools import update_requirements_doc

        mock_db = MagicMock()

        config = {"configurable": {"db": mock_db, "work_id": "", "emit": lambda e, d: None}}

        result = update_requirements_doc.func(content="新内容", config=config)
        assert "未绑定" in result or "不存在" in result


# ── Schema 验证 ──


class TestRequirementsDocSchemas:
    """验证需求文档工具的 Schema 定义"""

    def test_read_requirements_doc_has_no_content_param(self):
        """read_requirements_doc 不应有 content 参数"""
        from app.services.supervisor.tools import ReadRequirementsDocInput
        schema = ReadRequirementsDocInput.model_json_schema()
        props = schema.get("properties", {})
        assert "content" not in props

    def test_update_requirements_doc_has_content_param(self):
        """update_requirements_doc 应有 content 参数"""
        from app.services.supervisor.tools import UpdateRequirementsDocInput
        schema = UpdateRequirementsDocInput.model_json_schema()
        props = schema["properties"]
        assert "content" in props
        required = schema.get("required", [])
        assert "content" in required


# ── 数据库模型验证 ──


class TestWorkModelRequirementsDoc:
    """验证 works 表的 requirements_doc 字段"""

    def test_work_model_has_requirements_doc_field(self):
        """Work 模型应有 requirements_doc 字段"""
        from app.models.work_model import Work
        assert hasattr(Work, "requirements_doc")
