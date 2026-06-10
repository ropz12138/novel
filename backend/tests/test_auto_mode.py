"""测试 auto_mode 机制

验证：
1. SupervisorSession 模型有 auto_mode 字段
2. SupervisorStartRequest 接受 auto_mode 参数
3. 自动模式（默认）下，大纲编辑和章节编辑直接执行不等待确认
4. 手动模式（auto_mode=False）下，大纲编辑和章节编辑需要用户确认
5. auto_mode 从 session 正确传递到 config
6. dispatch_chapter 不再有 auto_apply 参数
7. outline 工具集中根据 auto_mode 决定是否包含 commit_or_rollback
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ────────────────────────── 1. 模型层测试 ──────────────────────────


class TestSupervisorSessionAutoMode:
    """验证 SupervisorSession 有 auto_mode 字段"""

    def test_auto_mode_column_exists(self):
        from app.models.agent_model import SupervisorSession
        col_names = [c.name for c in SupervisorSession.__table__.columns]
        assert "auto_mode" in col_names, f"auto_mode 不在 {col_names} 中"

    def test_auto_mode_default_true(self):
        from app.models.agent_model import SupervisorSession
        col = SupervisorSession.__table__.columns["auto_mode"]
        # 默认值应为 True（自动模式）
        assert col.default is not None
        assert col.default.arg is True or col.default.arg == "true"


# ────────────────────────── 2. Schema 测试 ──────────────────────────


class TestSupervisorStartRequestAutoMode:
    """验证 SupervisorStartRequest 接受 auto_mode 参数"""

    def test_start_request_has_auto_mode(self):
        from app.schemas.supervisor_schema import SupervisorStartRequest
        schema = SupervisorStartRequest.model_json_schema()
        props = schema["properties"]
        assert "auto_mode" in props, f"auto_mode 不在 {list(props.keys())} 中"

    def test_start_request_auto_mode_default_true(self):
        from app.schemas.supervisor_schema import SupervisorStartRequest
        req = SupervisorStartRequest(message="test")
        assert req.auto_mode is True

    def test_start_request_auto_mode_can_be_false(self):
        from app.schemas.supervisor_schema import SupervisorStartRequest
        req = SupervisorStartRequest(message="test", auto_mode=False)
        assert req.auto_mode is False


class TestSessionOutAutoMode:
    """验证 SupervisorSessionOut 包含 auto_mode"""

    def test_session_out_has_auto_mode(self):
        from app.schemas.session_schema import SupervisorSessionOut
        schema = SupervisorSessionOut.model_json_schema()
        props = schema["properties"]
        assert "auto_mode" in props, f"auto_mode 不在 {list(props.keys())} 中"


class TestDispatchChapterNoAutoApply:
    """验证 dispatch_chapter 没有 auto_apply 参数"""

    def test_dispatch_chapter_schema_no_auto_apply(self):
        from app.services.supervisor.tools import DispatchChapterInput
        schema = DispatchChapterInput.model_json_schema()
        props = schema["properties"]
        assert "auto_apply" not in props, f"auto_apply 仍存在于 {list(props.keys())} 中"

    def test_dispatch_chapter_schema_has_basic_fields(self):
        from app.services.supervisor.tools import DispatchChapterInput
        schema = DispatchChapterInput.model_json_schema()
        props = schema["properties"]
        assert "instruction" in props
        assert "work_id" in props
        assert "chapter_number" in props


# ────────────────────────── 3. 配置传递测试 ──────────────────────────


class TestAutoModeConfigPropagation:
    """验证 auto_mode 从 session 传递到 config"""

    def test_run_graph_config_contains_auto_mode_default(self):
        """_run_graph 的 config 中应包含 auto_mode（默认模式为 True）"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        mock_db = MagicMock()
        mock_emit = MagicMock()
        agent = SupervisorAgent(emit=mock_emit, db=mock_db, work_id="w1")

        # 创建一个 mock session（默认自动模式）
        mock_session = MagicMock()
        mock_session.id = "test-session"
        mock_session.auto_mode = True
        mock_session.work_id = "w1"
        mock_session.status = "running"

        # 验证 _run_graph 会把 auto_mode 放入 config
        # 我们通过 patch _build_graph 来验证 config
        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = AsyncMock()
            mock_graph.astream.return_value = iter([])  # 空流
            mock_build.return_value = mock_graph

            # 需要 patch message_service
            with patch("app.services.supervisor.supervisor_agent.message_service") as mock_msg:
                mock_msg.get_messages_by_session.return_value = []
                mock_msg.get_next_sort_order.return_value = 0
                mock_msg.create_message.return_value = None

                import asyncio
                asyncio.get_event_loop().run_until_complete(
                    agent._run_graph(mock_session, "test message")
                )

        # 验证 astream 被调用时的 config 参数
        call_args = mock_graph.astream.call_args
        config = call_args[1]["config"] if "config" in (call_args[1] or {}) else call_args[0][1]
        assert "configurable" in config
        assert config["configurable"].get("auto_mode") is True

    def test_run_graph_config_contains_auto_mode_false(self):
        """_run_graph 的 config 中应包含 auto_mode=False（手动模式）"""
        from app.services.supervisor.supervisor_agent import SupervisorAgent

        mock_db = MagicMock()
        mock_emit = MagicMock()
        agent = SupervisorAgent(emit=mock_emit, db=mock_db, work_id="w1")

        mock_session = MagicMock()
        mock_session.id = "test-session"
        mock_session.auto_mode = False
        mock_session.work_id = "w1"
        mock_session.status = "running"

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = AsyncMock()
            mock_graph.astream.return_value = iter([])
            mock_build.return_value = mock_graph

            with patch("app.services.supervisor.supervisor_agent.message_service") as mock_msg:
                mock_msg.get_messages_by_session.return_value = []
                mock_msg.get_next_sort_order.return_value = 0
                mock_msg.create_message.return_value = None

                import asyncio
                asyncio.get_event_loop().run_until_complete(
                    agent._run_graph(mock_session, "test message")
                )

        call_args = mock_graph.astream.call_args
        config = call_args[1]["config"] if "config" in (call_args[1] or {}) else call_args[0][1]
        assert config["configurable"].get("auto_mode") is False


# ────────────────────────── 4. 大纲编辑模式测试 ──────────────────────────


class TestOutlineEditMode:
    """验证大纲编辑在手动模式 vs 自动模式下的行为差异"""

    def test_outline_tools_manual_mode_excludes_commit(self):
        """手动模式（auto_mode=False）下，outline 工具集不应包含 commit_or_rollback"""
        from app.services.supervisor.outline_tools import build_outline_tools
        tools = build_outline_tools(auto_mode=False)
        tool_names = [t.name for t in tools]
        assert "commit_or_rollback" not in tool_names, (
            f"默认模式下不应包含 commit_or_rollback，实际包含: {tool_names}"
        )

    def test_outline_tools_auto_mode_includes_commit(self):
        """自动模式下，outline 工具集应包含 commit_or_rollback"""
        from app.services.supervisor.outline_tools import build_outline_tools
        tools = build_outline_tools(auto_mode=True)
        tool_names = [t.name for t in tools]
        assert "commit_or_rollback" in tool_names, (
            f"自动模式下应包含 commit_or_rollback，实际包含: {tool_names}"
        )

    def test_outline_tools_has_basic_tools(self):
        """两种模式都应有基本工具"""
        from app.services.supervisor.outline_tools import build_outline_tools
        for auto_mode in (True, False):
            tools = build_outline_tools(auto_mode=auto_mode)
            tool_names = {t.name for t in tools}
            assert "read_outline" in tool_names
            assert "query_outline_characters" in tool_names
            assert "edit_outline_by_suggestion" in tool_names
            assert "compute_diff" not in tool_names


class TestOutlineEditManualModeFlow:
    """手动模式下大纲编辑应返回 diff 信息并设置 waiting 状态"""

    @pytest.mark.asyncio
    async def test_edit_outline_manual_mode_returns_diff(self):
        """手动模式下 edit_outline 应返回 diff 信息"""
        from app.services.supervisor.tools import dispatch_outline

        mock_db = MagicMock()
        emitted = []

        def mock_emit(event, data):
            emitted.append({"event": event, "data": data})

        config = {
            "configurable": {
                "db": mock_db,
                "emit": mock_emit,
                "supervisor_session_id": "sess-1",
                "auto_mode": False,
            },
        }

        # mock SupervisorSession
        mock_sess = MagicMock()
        mock_sess.id = "sess-1"
        mock_sess.work_id = "w-1"
        sess_q = MagicMock()
        sess_q.filter_by.return_value.first.return_value = mock_sess
        mock_db.query.return_value = sess_q

        with patch(
            "app.services.supervisor.outline_agent.OutlineAgent.edit_outline",
            new_callable=AsyncMock,
        ) as mock_edit:
            mock_edit.return_value = {
                "outline_summary": {"total_added": 0, "total_modified": 5, "total_removed": 0},
                "character_summary": {"total_added": 0, "total_modified": 2, "total_removed": 0},
                "operations": [{"tool": "edit_outline"}],
            }
            result = await dispatch_outline.coroutine(
                message="修改大纲",
                work_id="w-1",
                config=config,
            )

        assert "等待用户确认" in result
        # session 应被设为 waiting 状态
        assert mock_sess.status == "waiting"


# ────────────────────────── 5. 章节编辑模式测试 ──────────────────────────


class TestChapterEditMode:
    """验证章节编辑在手动模式 vs 自动模式下的行为差异"""

    @pytest.mark.asyncio
    async def test_edit_chapter_manual_mode_sets_waiting(self):
        """手动模式下，编辑章节应设置 waiting 状态"""
        from app.services.supervisor.tools import dispatch_outline as _  # noqa: F401
        from app.services.supervisor.tools import dispatch_chapter

        mock_db = MagicMock()

        # 章节存在且有正文 → 走编辑逻辑
        mock_chapter = MagicMock()
        mock_chapter.content = "旧内容"
        mock_chapter.chapter_number = 2

        mock_sess = MagicMock()
        mock_sess.id = "sess-1"
        mock_sess.work_id = "w-1"

        def query_side_effect(model):
            q = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "Chapter":
                    q.filter_by.return_value.first.return_value = mock_chapter
                elif model.__name__ == "SupervisorSession":
                    q.filter_by.return_value.first.return_value = mock_sess
            return q

        mock_db.query.side_effect = query_side_effect

        config = {
            "configurable": {
                "db": mock_db,
                "emit": lambda e, d: None,
                "supervisor_session_id": "sess-1",
                "auto_mode": False,
            },
        }

        with patch(
            "app.services.supervisor.edit_chapter_agent.EditChapterAgent.run",
            new_callable=AsyncMock,
        ) as mock_run:
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

        assert "确认" in result or "修改" in result
        assert mock_sess.status == "waiting"

    @pytest.mark.asyncio
    async def test_edit_chapter_auto_mode_auto_applies(self):
        """自动模式下，编辑章节应直接保存不等待确认"""
        from app.services.supervisor.tools import dispatch_chapter

        mock_db = MagicMock()

        mock_chapter = MagicMock()
        mock_chapter.content = "旧内容"
        mock_chapter.chapter_number = 2

        mock_sess = MagicMock()
        mock_sess.id = "sess-1"
        mock_sess.work_id = "w-1"

        def query_side_effect(model):
            q = MagicMock()
            if hasattr(model, "__name__"):
                if model.__name__ == "Chapter":
                    q.filter_by.return_value.first.return_value = mock_chapter
                elif model.__name__ == "SupervisorSession":
                    q.filter_by.return_value.first.return_value = mock_sess
            return q

        mock_db.query.side_effect = query_side_effect

        emitted = []

        def mock_emit(event, data):
            emitted.append({"event": event, "data": data})

        config = {
            "configurable": {
                "db": mock_db,
                "emit": mock_emit,
                "supervisor_session_id": "sess-1",
                "auto_mode": True,
            },
        }

        with patch(
            "app.services.supervisor.edit_chapter_agent.EditChapterAgent.run",
            new_callable=AsyncMock,
        ) as mock_run:
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

        # 自动模式：session 不应被设为 waiting
        assert mock_sess.status != "waiting"
        # 应发出自动应用事件
        event_names = [e["event"] for e in emitted]
        assert "edit_chapter_auto_applied" in event_names


# ────────────────────────── 6. OutlineAgent prompt 测试 ──────────────────────────


class TestOutlinePromptAutoMode:
    """验证大纲 prompt 根据 auto_mode 有不同指令"""

    def test_manual_mode_prompt_no_commit_instruction(self):
        """手动模式的 prompt 不应要求 LLM 调用 commit_or_rollback"""
        from app.services.supervisor.outline_agent import _build_outline_system_prompt
        prompt = _build_outline_system_prompt(work_id="w-1", user_message="test", auto_mode=False)
        # 不应包含 "必须调用 commit" 等指令
        assert "commit_or_rollback" not in prompt or "不需要" in prompt or "不要" in prompt

    def test_auto_mode_prompt_has_commit_instruction(self):
        """自动模式的 prompt 应要求 LLM 调用 commit"""
        from app.services.supervisor.outline_agent import _build_outline_system_prompt
        prompt = _build_outline_system_prompt(work_id="w-1", user_message="test", auto_mode=True)
        # 应包含 commit 相关指令
        assert "commit" in prompt.lower() or "提交" in prompt


# ────────────────────────── 7. OutlineAgent edit_outline 返回值测试 ──────────────────────────


class TestOutlineEditReturnValues:
    """验证 OutlineAgent.edit_outline 在手动模式下正确返回 diff 信息"""

    @pytest.mark.asyncio
    async def test_edit_outline_manual_mode_collects_diff(self):
        """手动模式下 edit_outline 应从工具调用中收集并返回 diff 信息"""
        from app.services.supervisor.outline_agent import OutlineAgent

        emitted = []
        agent = OutlineAgent(emit=lambda e, d: emitted.append((e, d)))

        mock_db = MagicMock()

        # 我们需要模拟整个 LangGraph 的执行
        # 这里用 patch _build_graph 来控制
        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = AsyncMock()

            # 模拟 edit_outline 工具返回的 diff 信息
            async def mock_astream(*args, **kwargs):
                # 模拟 graph 产生事件
                yield {
                    "tools": {
                        "messages": [MagicMock(content="大纲变更已生成（大纲 +0/~5/-0）。变更已暂存。")],
                    }
                }

            mock_graph.astream = mock_astream
            mock_build.return_value = mock_graph

            result = await agent.edit_outline(
                work_id="w-1",
                message="修改大纲",
                history=[],
                db=mock_db,
            )

        # 手动模式下应返回包含 diff 信息的 dict
        assert isinstance(result, dict)
        # 应包含 outline_summary 和 character_summary
        assert "outline_summary" in result or "message" in result


class TestOutlineEditAutoModeNoDiffEmit:
    """自动模式下不应向前端发送需确认的 outline/character diff 事件"""

    @pytest.mark.asyncio
    async def test_edit_outline_auto_mode_suppresses_diff_sse(self):
        from app.services.supervisor.outline_agent import OutlineAgent

        emitted = []
        agent = OutlineAgent(emit=lambda e, d: emitted.append((e, d)))
        mock_db = MagicMock()

        with patch.object(agent, "_build_graph") as mock_build:
            mock_graph = AsyncMock()

            async def mock_astream(*args, **kwargs):
                # 模拟 capturing_emit 被工具层调用（经 graph tools 节点间接触发）
                agent.emit("outline_edit_diff", {"summary": {"total_added": 1}, "operations": []})
                agent.emit("character_edit_diff", {"summary": {"total_added": 0}, "diff": {}})
                yield {"agent": {"messages": []}}

            mock_graph.astream = mock_astream
            mock_build.return_value = mock_graph

            await agent.edit_outline(
                work_id="w-1",
                message="修改大纲",
                history=[],
                db=mock_db,
                auto_mode=True,
            )

        event_names = [e for e, _ in emitted]
        assert "outline_edit_diff" not in event_names
        assert "character_edit_diff" not in event_names
