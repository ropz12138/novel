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
        "outline": {
            "macro_phases": [
                {
                    "id": "P1",
                    "order": 1,
                    "name": "开端",
                    "goal": "主角发现异常",
                    "core_setting": "",
                    "chapter_range": [1, 10],
                },
                {
                    "id": "P2",
                    "order": 2,
                    "name": "发展",
                    "goal": "主角成长",
                    "core_setting": "",
                    "chapter_range": [11, 20],
                },
            ],
            "core_characters": [],
            "ending": {},
        },
        "meso": {
            "meso_stages": [
                {
                    "id": "M1",
                    "macro_phase_id": "P1",
                    "type": "left",
                    "name": "支线A",
                    "cause": "支线描述",
                    "conflict": "",
                    "key_characters": [],
                    "chapter_range": [3, 7],
                },
            ],
        },
        "foreshadowing": [
            {
                "id": "F1",
                "plant_node": "P1",
                "payoff_node": "P2",
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
            "first_appearance_stage": "M1",
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
            "first_appearance_stage": "M1",
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
        assert result["macro_phases"] == []
        assert result["meso_stages"] == []
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
        """新增宏观阶段"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["outline"]["macro_phases"].append({
            "id": "P3",
            "order": 3,
            "name": "高潮",
            "goal": "决战",
            "core_setting": "",
            "chapter_range": [21, 30],
        })

        result = compute_outline_diff(old, new)
        assert len(result["macro_phases"]) == 1
        assert result["macro_phases"][0]["type"] == "added"
        assert result["macro_phases"][0]["node_id"] == "P3"
        assert result["macro_phases"][0]["data"]["name"] == "高潮"

    def test_timeline_node_removed(self):
        """删除宏观阶段"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["outline"]["macro_phases"] = [new["outline"]["macro_phases"][0]]  # 只保留 P1

        result = compute_outline_diff(old, new)
        assert len(result["macro_phases"]) == 1
        assert result["macro_phases"][0]["type"] == "removed"
        assert result["macro_phases"][0]["node_id"] == "P2"
        assert result["macro_phases"][0]["data"]["name"] == "发展"

    def test_timeline_node_modified(self):
        """修改宏观阶段字段"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["outline"]["macro_phases"][0]["name"] = "新的开端"
        new["outline"]["macro_phases"][0]["chapter_range"] = [1, 15]

        result = compute_outline_diff(old, new)
        assert len(result["macro_phases"]) == 1
        assert result["macro_phases"][0]["type"] == "modified"
        assert result["macro_phases"][0]["node_id"] == "P1"
        changes = {c["field"]: c for c in result["macro_phases"][0]["changes"]}
        assert changes["name"]["old"] == "开端"
        assert changes["name"]["new"] == "新的开端"
        assert changes["chapter_range"]["old"] == [1, 10]
        assert changes["chapter_range"]["new"] == [1, 15]

    def test_timeline_mixed_operations(self):
        """同时有新增、修改、删除"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        # 修改 P1
        new["outline"]["macro_phases"][0]["goal"] = "新目标"
        # 删除 P2
        new["outline"]["macro_phases"] = [new["outline"]["macro_phases"][0]]
        # 新增 P3
        new["outline"]["macro_phases"].append({
            "id": "P3",
            "order": 2,
            "name": "新阶段",
            "goal": "",
            "core_setting": "",
            "chapter_range": [21, 30],
        })

        result = compute_outline_diff(old, new)
        types = {c["type"] for c in result["macro_phases"]}
        assert types == {"added", "modified", "removed"}

    def test_branch_added(self):
        """新增中纲阶段"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["meso"]["meso_stages"].append({
            "id": "M2",
            "macro_phase_id": "P2",
            "type": "right",
            "name": "中纲B",
            "cause": "",
            "conflict": "",
            "key_characters": [],
            "chapter_range": [11, 15],
        })

        result = compute_outline_diff(old, new)
        assert len(result["meso_stages"]) == 1
        assert result["meso_stages"][0]["type"] == "added"
        assert result["meso_stages"][0]["node_id"] == "M2"

    def test_branch_modified(self):
        """修改中纲阶段"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["meso"]["meso_stages"][0]["name"] = "新阶段名"

        result = compute_outline_diff(old, new)
        assert len(result["meso_stages"]) == 1
        assert result["meso_stages"][0]["type"] == "modified"
        assert result["meso_stages"][0]["changes"][0]["field"] == "name"

    def test_branch_removed(self):
        """删除中纲阶段"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["meso"]["meso_stages"] = []

        result = compute_outline_diff(old, new)
        assert len(result["meso_stages"]) == 1
        assert result["meso_stages"][0]["type"] == "removed"

    def test_foreshadowing_added(self):
        """新增伏笔"""
        from app.services.diff_service import compute_outline_diff

        old = _base_outline()
        new = _base_outline()
        new["foreshadowing"].append({
            "id": "F2",
            "plant_node": "P1",
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

        old = {"story": {}, "outline": {"macro_phases": []}, "meso": {"meso_stages": []}, "foreshadowing": []}
        new = {"story": {}, "outline": {"macro_phases": []}, "meso": {"meso_stages": []}, "foreshadowing": []}
        result = compute_outline_diff(old, new)
        assert result["story"] == []
        assert result["macro_phases"] == []

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
            "first_appearance_stage": "M5",
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
            "current_goal": "", "first_appearance_stage": "M1",
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
            "macro_phases": [],
            "meso_stages": [],
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
            "macro_phases": [
                {"type": "added", "node_id": "P3", "data": {}},
                {"type": "modified", "node_id": "P1", "changes": []},
                {"type": "removed", "node_id": "P2", "data": {}},
            ],
            "meso_stages": [],
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
        """大纲工具集应包含所有必要工具"""
        from app.services.supervisor.outline_tools import get_outline_tools
        tools = get_outline_tools(auto_mode=True)
        tool_names = {t.name for t in tools}
        # 核心读取工具
        assert "read_outline" in tool_names
        assert "read_macro_outline" in tool_names
        assert "read_meso_outline" in tool_names
        assert "read_micro_outline" in tool_names
        # 核心生成工具
        assert "generate_macro_outline" in tool_names
        assert "generate_meso_outline" in tool_names
        assert "generate_micro_outline" in tool_names
        assert len(tools) >= 10


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
                "outline_diff": {"story": [{"type": "modified"}], "macro_phases": [], "meso_stages": [], "foreshadowing": []},
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
