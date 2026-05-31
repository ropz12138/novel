"""测试 diff_service — 大纲 diff 与角色 diff 生成

覆盖：
1. compute_outline_diff：对比新旧 outline_tree，生成结构化变更列表
2. compute_character_diff：对比新旧角色列表，生成角色变更列表
3. summarize_diff：生成变更摘要统计
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── 辅助：构造测试数据 ──


def _base_outline():
    """基础大纲（修改前）"""
    return {
        "story": {"title": "旧标题", "genre": "玄幻", "volume": "第一卷"},
        "timeline": [
            {
                "id": "N1",
                "order": 1,
                "development_node": "开端",
                "summary": "主角发现异常",
                "time_node": "初期",
                "chapter_start": 1,
                "chapter_end": 10,
            },
            {
                "id": "N2",
                "order": 2,
                "development_node": "发展",
                "summary": "主角成长",
                "time_node": "中期",
                "chapter_start": 11,
                "chapter_end": 20,
            },
        ],
        "branches": [
            {
                "id": "B1",
                "attach_to": "N1",
                "side": "left",
                "name": "支线A",
                "summary": "支线描述",
                "chapter_start": 3,
                "chapter_end": 7,
            },
        ],
        "foreshadowing": [
            {
                "id": "F1",
                "plant_node": "N1",
                "payoff_node": "N2",
                "content": "伏笔内容",
            },
        ],
    }


def _base_characters():
    """基础角色列表（修改前）"""
    return [
        {
            "name": "张三",
            "role_type": "主角",
            "gender": "男",
            "age": "18",
            "appearance": "英俊",
            "personality": "勇敢",
            "background": "孤儿",
            "skills": "剑术",
            "current_status": "存活",
            "current_goal": "复仇",
            "first_chapter": 1,
        },
        {
            "name": "李四",
            "role_type": "配角",
            "gender": "女",
            "age": "17",
            "appearance": "美丽",
            "personality": "温柔",
            "background": "贵族",
            "skills": "魔法",
            "current_status": "存活",
            "current_goal": "寻找真相",
            "first_chapter": 1,
        },
    ]


# ── 1. compute_outline_diff 测试 ──


class TestComputeOutlineDiff:
    """大纲 diff 对比函数测试"""

    def test_no_changes(self):
        """新旧大纲完全相同时，变更列表为空"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        result = compute_outline_diff(old, new)
        assert result["story"] == []
        assert result["timeline"] == []
        assert result["branches"] == []
        assert result["foreshadowing"] == []

    def test_story_modified(self):
        """story 字段修改"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["story"]["title"] = "新标题"
        new["story"]["genre"] = "科幻"

        result = compute_outline_diff(old, new)
        assert len(result["story"]) == 2
        # 验证每项变更
        story_changes = {c["field"]: c for c in result["story"]}
        assert story_changes["title"]["type"] == "modified"
        assert story_changes["title"]["old"] == "旧标题"
        assert story_changes["title"]["new"] == "新标题"
        assert story_changes["genre"]["type"] == "modified"
        assert story_changes["genre"]["old"] == "玄幻"
        assert story_changes["genre"]["new"] == "科幻"

    def test_story_new_field_added(self):
        """story 中新增了原来没有的字段"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["story"]["subtitle"] = "副标题"

        result = compute_outline_diff(old, new)
        assert len(result["story"]) == 1
        assert result["story"][0]["type"] == "added"
        assert result["story"][0]["field"] == "subtitle"
        assert result["story"][0]["new"] == "副标题"

    def test_story_field_removed(self):
        """story 中删除了某个字段"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        del new["story"]["volume"]

        result = compute_outline_diff(old, new)
        assert len(result["story"]) == 1
        assert result["story"][0]["type"] == "removed"
        assert result["story"][0]["field"] == "volume"
        assert result["story"][0]["old"] == "第一卷"

    def test_timeline_node_added(self):
        """新增主线节点"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["timeline"].append({
            "id": "N3",
            "order": 3,
            "development_node": "高潮",
            "summary": "决战",
            "time_node": "后期",
            "chapter_start": 21,
            "chapter_end": 30,
        })

        result = compute_outline_diff(old, new)
        assert len(result["timeline"]) == 1
        assert result["timeline"][0]["type"] == "added"
        assert result["timeline"][0]["node_id"] == "N3"
        assert result["timeline"][0]["data"]["development_node"] == "高潮"

    def test_timeline_node_removed(self):
        """删除主线节点"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["timeline"] = [new["timeline"][0]]  # 只保留 N1

        result = compute_outline_diff(old, new)
        assert len(result["timeline"]) == 1
        assert result["timeline"][0]["type"] == "removed"
        assert result["timeline"][0]["node_id"] == "N2"
        assert result["timeline"][0]["data"]["development_node"] == "发展"

    def test_timeline_node_modified(self):
        """修改主线节点字段"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["timeline"][0]["development_node"] = "新的开端"
        new["timeline"][0]["chapter_end"] = 15

        result = compute_outline_diff(old, new)
        assert len(result["timeline"]) == 1
        assert result["timeline"][0]["type"] == "modified"
        assert result["timeline"][0]["node_id"] == "N1"
        changes = {c["field"]: c for c in result["timeline"][0]["changes"]}
        assert changes["development_node"]["old"] == "开端"
        assert changes["development_node"]["new"] == "新的开端"
        assert changes["chapter_end"]["old"] == 10
        assert changes["chapter_end"]["new"] == 15

    def test_timeline_mixed_operations(self):
        """同时有新增、修改、删除"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        # 修改 N1
        new["timeline"][0]["summary"] = "新摘要"
        # 删除 N2
        new["timeline"] = [new["timeline"][0]]
        # 新增 N3
        new["timeline"].append({
            "id": "N3",
            "order": 2,
            "development_node": "新节点",
            "summary": "",
            "time_node": "后期",
            "chapter_start": 21,
            "chapter_end": 30,
        })

        result = compute_outline_diff(old, new)
        types = {c["type"] for c in result["timeline"]}
        assert types == {"added", "modified", "removed"}

    def test_branch_added(self):
        """新增支线"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["branches"].append({
            "id": "B2",
            "attach_to": "N2",
            "side": "right",
            "name": "支线B",
            "summary": "",
            "chapter_start": 11,
            "chapter_end": 15,
        })

        result = compute_outline_diff(old, new)
        assert len(result["branches"]) == 1
        assert result["branches"][0]["type"] == "added"
        assert result["branches"][0]["node_id"] == "B2"

    def test_branch_modified(self):
        """修改支线"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["branches"][0]["name"] = "新支线名"

        result = compute_outline_diff(old, new)
        assert len(result["branches"]) == 1
        assert result["branches"][0]["type"] == "modified"
        assert result["branches"][0]["changes"][0]["field"] == "name"

    def test_branch_removed(self):
        """删除支线"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["branches"] = []

        result = compute_outline_diff(old, new)
        assert len(result["branches"]) == 1
        assert result["branches"][0]["type"] == "removed"

    def test_foreshadowing_added(self):
        """新增伏笔"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["foreshadowing"].append({
            "id": "F2",
            "plant_node": "N1",
            "payoff_node": "N3",
            "content": "新伏笔",
        })

        result = compute_outline_diff(old, new)
        assert len(result["foreshadowing"]) == 1
        assert result["foreshadowing"][0]["type"] == "added"
        assert result["foreshadowing"][0]["data"]["content"] == "新伏笔"

    def test_foreshadowing_modified(self):
        """修改伏笔"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["foreshadowing"][0]["content"] = "新的伏笔内容"

        result = compute_outline_diff(old, new)
        assert len(result["foreshadowing"]) == 1
        assert result["foreshadowing"][0]["type"] == "modified"

    def test_foreshadowing_removed(self):
        """删除伏笔"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["foreshadowing"] = []

        result = compute_outline_diff(old, new)
        assert len(result["foreshadowing"]) == 1
        assert result["foreshadowing"][0]["type"] == "removed"

    def test_empty_outlines(self):
        """空大纲对比"""
        from app.services.diff_service import compute_outline_diff

        old = {"story": {}, "timeline": [], "branches": [], "foreshadowing": []}
        new = {"story": {}, "timeline": [], "branches": [], "foreshadowing": []}
        result = compute_outline_diff(old, new)
        assert result["story"] == []
        assert result["timeline"] == []

    def test_none_values_handled(self):
        """字段值为 None 时正常处理"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["story"]["title"] = None

        result = compute_outline_diff(old, new)
        assert len(result["story"]) == 1
        assert result["story"][0]["new"] is None


# ── 2. compute_character_diff 测试 ──


class TestComputeCharacterDiff:
    """角色 diff 对比函数测试"""

    def test_no_changes(self):
        """新旧角色完全相同时，变更列表为空"""
        from app.services.diff_service import compute_character_diff

        old = _base_characters()
        new = _base_characters()
        result = compute_character_diff(old, new)
        assert result["changes"] == []

    def test_character_added(self):
        """新增角色"""
        from app.services.diff_service import compute_character_diff

        old = _base_characters()
        new = _base_characters()
        new.append({
            "name": "王五",
            "role_type": "反派",
            "gender": "男",
            "age": "30",
            "appearance": "阴沉",
            "personality": "狡猾",
            "background": "神秘",
            "skills": "暗杀",
            "current_status": "存活",
            "current_goal": "称霸",
            "first_chapter": 5,
        })

        result = compute_character_diff(old, new)
        assert len(result["changes"]) == 1
        assert result["changes"][0]["type"] == "added"
        assert result["changes"][0]["name"] == "王五"
        assert result["changes"][0]["data"]["role_type"] == "反派"

    def test_character_removed(self):
        """删除角色"""
        from app.services.diff_service import compute_character_diff

        old = _base_characters()
        new = [_base_characters()[0]]  # 只保留张三

        result = compute_character_diff(old, new)
        assert len(result["changes"]) == 1
        assert result["changes"][0]["type"] == "removed"
        assert result["changes"][0]["name"] == "李四"

    def test_character_modified(self):
        """修改角色字段"""
        from app.services.diff_service import compute_character_diff

        old = _base_characters()
        new = _base_characters()
        new[0]["personality"] = "沉稳"
        new[0]["age"] = "20"

        result = compute_character_diff(old, new)
        assert len(result["changes"]) == 1
        assert result["changes"][0]["type"] == "modified"
        assert result["changes"][0]["name"] == "张三"
        changes = {c["field"]: c for c in result["changes"][0]["changes"]}
        assert changes["personality"]["old"] == "勇敢"
        assert changes["personality"]["new"] == "沉稳"
        assert changes["age"]["old"] == "18"
        assert changes["age"]["new"] == "20"

    def test_character_name_changed(self):
        """角色改名 — 视为删除旧角色 + 新增新角色（因为 name 是匹配键）"""
        from app.services.diff_service import compute_character_diff

        old = _base_characters()
        new = _base_characters()
        new[0]["name"] = "张三丰"

        result = compute_character_diff(old, new)
        types = {c["type"] for c in result["changes"]}
        assert "removed" in types
        assert "added" in types

    def test_mixed_character_operations(self):
        """同时新增、修改、删除角色"""
        from app.services.diff_service import compute_character_diff

        old = _base_characters()
        new = list(_base_characters())
        # 修改李四
        new[1]["personality"] = "坚强"
        # 新增王五
        new.append({
            "name": "王五", "role_type": "反派", "gender": "男",
            "age": "30", "appearance": "", "personality": "狡猾",
            "background": "", "skills": "", "current_status": "存活",
            "current_goal": "", "first_chapter": 1,
        })

        result = compute_character_diff(old, new)
        types = {c["type"] for c in result["changes"]}
        assert types == {"added", "modified"}

    def test_empty_characters(self):
        """空角色列表对比"""
        from app.services.diff_service import compute_character_diff

        result = compute_character_diff([], [])
        assert result["changes"] == []

    def test_character_new_field_added(self):
        """角色新增了原来没有的字段"""
        from app.services.diff_service import compute_character_diff

        old = [{"name": "张三", "role_type": "主角"}]
        new = [{"name": "张三", "role_type": "主角", "personality": "勇敢"}]

        result = compute_character_diff(old, new)
        assert len(result["changes"]) == 1
        assert result["changes"][0]["type"] == "modified"
        assert result["changes"][0]["changes"][0]["field"] == "personality"
        assert result["changes"][0]["changes"][0]["type"] == "added"


# ── 3. summarize_diff 测试 ──


class TestSummarizeDiff:
    """diff 摘要统计测试"""

    def test_outline_diff_summary_all_zeros(self):
        """无变更时摘要全为 0"""
        from app.services.diff_service import summarize_outline_diff

        diff = {
            "story": [],
            "timeline": [],
            "branches": [],
            "foreshadowing": [],
        }
        result = summarize_outline_diff(diff)
        assert result["total_added"] == 0
        assert result["total_modified"] == 0
        assert result["total_removed"] == 0

    def test_outline_diff_summary_counts(self):
        """正确统计各类操作数量"""
        from app.services.diff_service import summarize_outline_diff

        diff = {
            "story": [
                {"type": "modified", "field": "title", "old": "旧", "new": "新"},
            ],
            "timeline": [
                {"type": "added", "node_id": "N3", "data": {}},
                {"type": "modified", "node_id": "N1", "changes": []},
                {"type": "removed", "node_id": "N2", "data": {}},
            ],
            "branches": [],
            "foreshadowing": [
                {"type": "removed", "node_id": "F1", "data": {}},
            ],
        }
        result = summarize_outline_diff(diff)
        assert result["total_added"] == 1
        assert result["total_modified"] == 2
        assert result["total_removed"] == 2
        assert result["total_changes"] == 5

    def test_character_diff_summary_counts(self):
        """角色 diff 摘要统计"""
        from app.services.diff_service import summarize_character_diff

        diff = {
            "changes": [
                {"type": "added", "name": "王五", "data": {}},
                {"type": "modified", "name": "张三", "changes": []},
                {"type": "removed", "name": "李四"},
            ],
        }
        result = summarize_character_diff(diff)
        assert result["total_added"] == 1
        assert result["total_modified"] == 1
        assert result["total_removed"] == 1
        assert result["total_changes"] == 3

    def test_character_diff_summary_empty(self):
        """空角色 diff 摘要"""
        from app.services.diff_service import summarize_character_diff

        result = summarize_character_diff({"changes": []})
        assert result["total_changes"] == 0


# ── 4. OutlineAgent 两阶段流程测试 ──


class TestOutlineAgentTwoPhaseFlow:
    """验证 OutlineAgent 改造后仍具备正确的基础能力"""

    def test_outline_agent_builds_graph(self):
        """OutlineAgent 应能成功构建 LangGraph"""
        from app.services.supervisor.outline_agent import OutlineAgent
        agent = OutlineAgent(emit=lambda e, d: None)
        graph = agent._build_graph()
        assert graph is not None

    def test_outline_agent_has_static_methods(self):
        """commit/rollback 静态方法应存在"""
        from app.services.supervisor.outline_agent import OutlineAgent
        assert hasattr(OutlineAgent, "commit_outline_edit")
        assert hasattr(OutlineAgent, "rollback_outline_edit")

    def test_outline_tools_count(self):
        """大纲工具集应有 10 个工具（包含 read_requirements_doc）"""
        from app.services.supervisor.outline_tools import get_outline_tools
        tools = get_outline_tools(auto_mode=True)
        assert len(tools) == 10


# ── 5. dispatch_outline 确认流程测试 ──


class TestDispatchOutlineConfirmFlow:
    """验证 dispatch_outline 的确认流程"""

    @pytest.mark.asyncio
    async def test_dispatch_outline_edit_sets_waiting(self):
        """编辑大纲后，session 状态应为 waiting"""
        from app.services.supervisor.tools import dispatch_outline

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.id = "sess-1"
        mock_session.work_id = "w-1"

        # session 查询
        sess_q = MagicMock()
        sess_q.filter_by.return_value.first.return_value = mock_session

        def query_side_effect(model):
            return sess_q

        mock_db.query.side_effect = query_side_effect

        config = {
            "configurable": {
                "db": mock_db,
                "emit": lambda e, d: None,
                "supervisor_session_id": "sess-1",
            },
        }

        with patch(
            "app.services.supervisor.outline_agent.OutlineAgent.edit_outline",
            new_callable=AsyncMock,
        ) as mock_edit:
            mock_edit.return_value = {
                "message": "已修改",
                "operations": [],
                "outline_diff": {"story": [{"type": "modified"}], "timeline": [], "branches": [], "foreshadowing": []},
                "character_diff": {"changes": []},
                "new_outline": _base_outline(),
            }
            result = await dispatch_outline.coroutine(
                message="修改大纲",
                work_id="w-1",
                config=config,
            )

        assert "等待用户确认" in result or "确认" in result


# ── 6. Supervisor confirm 端点 — 大纲/角色确认测试 ──


class TestSupervisorConfirmOutline:
    """验证 /supervisor/confirm 支持大纲和角色确认"""

    def test_confirm_outline_accept(self):
        """确认大纲修改"""
        from app.routers.supervisor_router import confirm_action
        from app.schemas.supervisor_schema import SupervisorConfirmRequest

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.status = "waiting"
        mock_session.active_child = {
            "type": "edit_outline",
            "work_id": "w-1",
            "new_outline": _base_outline(),
        }
        mock_session.work_id = "w-1"

        # work 查询
        mock_work = MagicMock()
        mock_work.outline_tree = {}
        work_q = MagicMock()
        work_q.filter_by.return_value.first.return_value = mock_work

        # session 查询
        sess_q = MagicMock()
        sess_q.filter_by.return_value.first.return_value = mock_session

        call_count = 0

        def query_side_effect(model):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return sess_q
            return work_q

        mock_db.query.side_effect = query_side_effect

        payload = SupervisorConfirmRequest(
            session_id="sess-1",
            action="accept",
        )

        result = confirm_action(payload, db=mock_db)
        assert result["status"] == "accepted"

    def test_confirm_outline_reject(self):
        """拒绝大纲修改"""
        from app.routers.supervisor_router import confirm_action
        from app.schemas.supervisor_schema import SupervisorConfirmRequest

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.status = "waiting"
        mock_session.active_child = {
            "type": "edit_outline",
            "work_id": "w-1",
            "new_outline": _base_outline(),
        }
        mock_session.work_id = "w-1"

        sess_q = MagicMock()
        sess_q.filter_by.return_value.first.return_value = mock_session

        def query_side_effect(model):
            return sess_q

        mock_db.query.side_effect = query_side_effect

        payload = SupervisorConfirmRequest(
            session_id="sess-1",
            action="reject",
        )

        result = confirm_action(payload, db=mock_db)
        assert result["status"] == "rejected"

    def test_confirm_outline_accept_with_character_changes(self):
        """确认大纲修改（含角色变更）"""
        from app.routers.supervisor_router import confirm_action
        from app.schemas.supervisor_schema import SupervisorConfirmRequest

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.status = "waiting"
        mock_session.active_child = {
            "type": "edit_outline",
            "work_id": "w-1",
        }
        mock_session.work_id = "w-1"

        sess_q = MagicMock()
        sess_q.filter_by.return_value.first.return_value = mock_session

        def query_side_effect(model):
            return sess_q

        mock_db.query.side_effect = query_side_effect

        payload = SupervisorConfirmRequest(
            session_id="sess-1",
            action="accept",
        )

        result = confirm_action(payload, db=mock_db)
        assert result["status"] == "accepted"
        assert result["type"] == "edit_outline"

    def test_confirm_unsupported_type(self):
        """不支持的操作类型应返回 400"""
        from app.routers.supervisor_router import confirm_action
        from app.schemas.supervisor_schema import SupervisorConfirmRequest
        from fastapi import HTTPException

        mock_db = MagicMock()
        mock_session = MagicMock()
        mock_session.status = "waiting"
        mock_session.active_child = {
            "type": "unknown_type",
        }

        sess_q = MagicMock()
        sess_q.filter_by.return_value.first.return_value = mock_session

        def query_side_effect(model):
            return sess_q

        mock_db.query.side_effect = query_side_effect

        payload = SupervisorConfirmRequest(
            session_id="sess-1",
            action="accept",
        )

        with pytest.raises(HTTPException) as exc_info:
            confirm_action(payload, db=mock_db)
        assert exc_info.value.status_code == 400
