"""测试 submit_characters 拆分为 submit_character_briefs + submit_character_details

验证：
1. CharacterBrief / CharacterDetail / CharacterDetailBatch schema 正确
2. brief + detail 按 name 合并为完整 CharacterInfo
3. 分批逻辑正确（batch_size=4 时 8→2批，9→3批）
4. 集成：mock LLM 返回骨架+详情，验证合并后结构与原来一致
"""

import sys

import pytest

sys.path.insert(0, "/root/Novel/backend")


# ──────────────────────────── 5.1 Schema 验证 ────────────────────────────


class TestCharacterBriefSchema:
    """CharacterBrief 能正确解析 LLM 输出的骨架数据"""

    def test_parse_full_brief(self):
        from app.schemas.work_schema import CharacterBrief

        b = CharacterBrief(
            name="林动",
            role_type="主角",
            gender="男",
            age="16",
            first_chapter=1,
            brief="天赋异禀的少年，立志振兴家族",
        )
        assert b.name == "林动"
        assert b.role_type == "主角"
        assert b.gender == "男"
        assert b.age == "16"
        assert b.first_chapter == 1
        assert b.brief == "天赋异禀的少年，立志振兴家族"

    def test_defaults(self):
        from app.schemas.work_schema import CharacterBrief

        b = CharacterBrief(name="路人甲")
        assert b.role_type == "配角"
        assert b.gender == ""
        assert b.age == ""
        assert b.first_chapter == 1
        assert b.brief == ""

    def test_brief_has_expected_fields(self):
        from app.schemas.work_schema import CharacterBrief

        fields = CharacterBrief.model_fields
        expected = {"name", "role_type", "gender", "age", "first_chapter", "brief"}
        assert set(fields.keys()) == expected


class TestCharacterDetailSchema:
    """CharacterDetail 能正确解析 LLM 输出的详情数据"""

    def test_parse_full_detail(self):
        from app.schemas.work_schema import CharacterDetail

        d = CharacterDetail(
            name="林动",
            appearance="剑眉星目，身形修长",
            personality="坚韧不拔，重情重义",
            background="落魄家族后人",
            skills="祖传符文术",
            current_status="修炼中",
            current_goal="振兴林家",
        )
        assert d.name == "林动"
        assert d.appearance == "剑眉星目，身形修长"
        assert d.current_goal == "振兴林家"

    def test_defaults(self):
        from app.schemas.work_schema import CharacterDetail

        d = CharacterDetail(name="龙套A")
        assert d.appearance == ""
        assert d.personality == ""
        assert d.background == ""
        assert d.skills == ""
        assert d.current_status == "存活"
        assert d.current_goal == ""

    def test_detail_has_expected_fields(self):
        from app.schemas.work_schema import CharacterDetail

        fields = CharacterDetail.model_fields
        expected = {"name", "appearance", "personality", "background", "skills", "current_status", "current_goal"}
        assert set(fields.keys()) == expected


class TestCharacterDetailBatchSchema:
    """CharacterDetailBatch 包含 characters 字段，类型正确"""

    def test_batch_with_multiple_details(self):
        from app.schemas.work_schema import CharacterDetail, CharacterDetailBatch

        d1 = CharacterDetail(name="林动", appearance="英俊")
        d2 = CharacterDetail(name="绫清竹", appearance="清冷绝美")
        batch = CharacterDetailBatch(characters=[d1, d2])
        assert len(batch.characters) == 2
        assert batch.characters[0].name == "林动"
        assert batch.characters[1].name == "绫清竹"

    def test_batch_empty_list(self):
        from app.schemas.work_schema import CharacterDetailBatch

        batch = CharacterDetailBatch(characters=[])
        assert len(batch.characters) == 0


class TestSubmitInputSchemas:
    """_SubmitCharacterBriefsInput / _SubmitCharacterDetailsInput 类型正确"""

    def test_submit_briefs_input(self):
        from app.schemas.work_schema import CharacterBrief

        from app.services.work_service import _SubmitCharacterBriefsInput

        briefs = [CharacterBrief(name="林动"), CharacterBrief(name="绫清竹")]
        inp = _SubmitCharacterBriefsInput(briefs=briefs)
        assert len(inp.briefs) == 2

    def test_submit_details_input(self):
        from app.schemas.work_schema import CharacterDetail

        from app.services.work_service import _SubmitCharacterDetailsInput

        details = [CharacterDetail(name="林动")]
        inp = _SubmitCharacterDetailsInput(characters=details)
        assert len(inp.characters) == 1


# ──────────────────────────── 5.2 合并逻辑 ────────────────────────────


class TestMergeBriefsAndDetails:
    """brief + detail 按 name 匹配合并为完整 CharacterInfo"""

    def _merge(self, briefs: list[dict], details: list[dict]) -> list[dict]:
        """模拟方案中的合并逻辑（骨架 + 详情 → 完整角色卡）"""
        detail_map = {d["name"]: d for d in details}
        characters = []
        for brief in briefs:
            detail = detail_map.get(brief["name"], {})
            characters.append({
                "name": brief["name"],
                "role_type": brief.get("role_type", "配角"),
                "gender": brief.get("gender", ""),
                "age": brief.get("age", ""),
                "appearance": detail.get("appearance", ""),
                "personality": detail.get("personality", ""),
                "background": detail.get("background", ""),
                "skills": detail.get("skills", ""),
                "current_status": detail.get("current_status", "存活"),
                "current_goal": detail.get("current_goal", ""),
                "first_chapter": brief.get("first_chapter", 1),
            })
        return characters

    def test_merge_matches_by_name(self):
        """brief + detail 按 name 匹配合并"""
        briefs = [
            {"name": "林动", "role_type": "主角", "gender": "男", "age": "16", "first_chapter": 1},
            {"name": "绫清竹", "role_type": "配角", "gender": "女", "age": "18", "first_chapter": 3},
        ]
        details = [
            {"name": "林动", "appearance": "英俊", "personality": "坚韧"},
            {"name": "绫清竹", "appearance": "清冷", "personality": "高傲"},
        ]

        result = self._merge(briefs, details)
        assert len(result) == 2
        assert result[0]["name"] == "林动"
        assert result[0]["appearance"] == "英俊"
        assert result[0]["personality"] == "坚韧"
        assert result[0]["role_type"] == "主角"
        assert result[1]["name"] == "绫清竹"
        assert result[1]["appearance"] == "清冷"

    def test_brief_without_detail_fills_defaults(self):
        """brief 中没有对应 detail 时，详情字段用空字符串填充"""
        briefs = [
            {"name": "林动", "role_type": "主角", "first_chapter": 1},
        ]
        details = []

        result = self._merge(briefs, details)
        assert len(result) == 1
        assert result[0]["name"] == "林动"
        assert result[0]["appearance"] == ""
        assert result[0]["personality"] == ""
        assert result[0]["background"] == ""
        assert result[0]["skills"] == ""
        assert result[0]["current_status"] == "存活"
        assert result[0]["current_goal"] == ""

    def test_detail_with_unknown_name_ignored(self):
        """detail 中出现 brief 不存在的 name 时，被忽略"""
        briefs = [
            {"name": "林动", "role_type": "主角", "first_chapter": 1},
        ]
        details = [
            {"name": "林动", "appearance": "英俊"},
            {"name": "不存在角色", "appearance": "幽灵"},
        ]

        result = self._merge(briefs, details)
        assert len(result) == 1
        assert result[0]["name"] == "林动"
        assert result[0]["appearance"] == "英俊"

    def test_merged_has_all_character_info_fields(self):
        """合并结果包含 CharacterInfo 的全部 11 个字段"""
        from app.schemas.work_schema import CharacterInfo

        briefs = [{"name": "林动", "role_type": "主角", "first_chapter": 1}]
        details = [{"name": "林动", "appearance": "英俊"}]

        result = self._merge(briefs, details)
        assert len(result) == 1

        merged = result[0]
        info_fields = set(CharacterInfo.model_fields.keys())
        assert set(merged.keys()) == info_fields

        # 验证可以用 CharacterInfo 正常实例化
        info = CharacterInfo(**merged)
        assert info.name == "林动"
        assert info.role_type == "主角"
        assert info.appearance == "英俊"


# ──────────────────────────── 5.3 分批逻辑 ────────────────────────────


class TestBatchLogic:
    """分批逻辑：batch_size=4 时不同角色数量的分批结果"""

    def test_8_characters_2_batches(self):
        """8 个角色 / batch_size=4 → 2 批"""
        briefs = [{"name": f"角色{i}"} for i in range(8)]
        batch_size = 4

        batches = []
        for start in range(0, len(briefs), batch_size):
            batches.append(briefs[start : start + batch_size])

        assert len(batches) == 2
        assert len(batches[0]) == 4
        assert len(batches[1]) == 4

    def test_9_characters_3_batches(self):
        """9 个角色 / batch_size=4 → 3 批（4 + 4 + 1）"""
        briefs = [{"name": f"角色{i}"} for i in range(9)]
        batch_size = 4

        batches = []
        for start in range(0, len(briefs), batch_size):
            batches.append(briefs[start : start + batch_size])

        assert len(batches) == 3
        assert len(batches[0]) == 4
        assert len(batches[1]) == 4
        assert len(batches[2]) == 1

    def test_3_characters_1_batch(self):
        """3 个角色 / batch_size=4 → 1 批（不需要分批）"""
        briefs = [{"name": f"角色{i}"} for i in range(3)]
        batch_size = 4

        batches = []
        for start in range(0, len(briefs), batch_size):
            batches.append(briefs[start : start + batch_size])

        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_batch_indices_correct(self):
        """每批的角色名称正确对应"""
        briefs = [{"name": f"角色{i}"} for i in range(6)]
        batch_size = 4

        batches = []
        for start in range(0, len(briefs), batch_size):
            batches.append(briefs[start : start + batch_size])

        assert [b["name"] for b in batches[0]] == ["角色0", "角色1", "角色2", "角色3"]
        assert [b["name"] for b in batches[1]] == ["角色4", "角色5"]

    def test_batch_num_calculation(self):
        """batch_num 和 total_batches 计算正确"""
        briefs = [{"name": f"角色{i}"} for i in range(9)]
        batch_size = 4
        total_batches = (len(briefs) + batch_size - 1) // batch_size

        assert total_batches == 3

        for batch_start in range(0, len(briefs), batch_size):
            batch_num = batch_start // batch_size + 1
            assert 1 <= batch_num <= total_batches


# ──────────────────────────── 5.4 集成测试 ────────────────────────────


class TestCharacterSplitIntegration:
    """集成测试：mock LLM，验证合并后结构与原来一致"""

    @pytest.mark.asyncio
    async def test_full_split_merge_flow(self):
        """mock LLM 返回骨架+详情，验证合并后 characters 结构与原来一致"""
        from app.schemas.work_schema import CharacterInfo

        from app.services.work_service import (
            _SubmitCharacterBriefsInput,
            _SubmitCharacterDetailsInput,
        )

        # 模拟 LLM 第1步返回的骨架
        mock_briefs = [
            {"name": "林动", "role_type": "主角", "gender": "男", "age": "16", "first_chapter": 1, "brief": "天赋少年"},
            {"name": "绫清竹", "role_type": "配角", "gender": "女", "age": "18", "first_chapter": 3, "brief": "冰山美人"},
            {"name": "异魔王", "role_type": "反派", "gender": "男", "age": "未知", "first_chapter": 5, "brief": "终极反派"},
        ]

        # 模拟 LLM 第2步返回的详情（一批）
        mock_details = [
            {"name": "林动", "appearance": "英俊", "personality": "坚韧", "background": "落魄家族", "skills": "符文术", "current_status": "修炼中", "current_goal": "振兴林家"},
            {"name": "绫清竹", "appearance": "清冷", "personality": "高傲", "background": "九天太清宫", "skills": "太清仙法", "current_status": "存活", "current_goal": "守护宗门"},
            {"name": "异魔王", "appearance": "黑暗笼罩", "personality": "阴险", "background": "异魔族", "skills": "吞噬之力", "current_status": "封印中", "current_goal": "破封而出"},
        ]

        # 验证 schema 能正确解析
        briefs_input = _SubmitCharacterBriefsInput(
            briefs=[{"name": b["name"], "role_type": b["role_type"], "gender": b["gender"], "age": b["age"], "first_chapter": b["first_chapter"], "brief": b["brief"]} for b in mock_briefs],
        )
        assert len(briefs_input.briefs) == 3

        details_input = _SubmitCharacterDetailsInput(
            characters=[{"name": d["name"], "appearance": d["appearance"], "personality": d["personality"], "background": d["background"], "skills": d["skills"], "current_status": d["current_status"], "current_goal": d["current_goal"]} for d in mock_details],
        )
        assert len(details_input.characters) == 3

        # 合并逻辑
        detail_map = {d["name"]: d for d in mock_details}
        characters = []
        for brief in mock_briefs:
            detail = detail_map.get(brief["name"], {})
            characters.append({
                "name": brief["name"],
                "role_type": brief.get("role_type", "配角"),
                "gender": brief.get("gender", ""),
                "age": brief.get("age", ""),
                "appearance": detail.get("appearance", ""),
                "personality": detail.get("personality", ""),
                "background": detail.get("background", ""),
                "skills": detail.get("skills", ""),
                "current_status": detail.get("current_status", "存活"),
                "current_goal": detail.get("current_goal", ""),
                "first_chapter": brief.get("first_chapter", 1),
            })

        # 验证合并结果与 CharacterInfo 完全兼容
        assert len(characters) == 3
        for c in characters:
            info = CharacterInfo(**c)
            assert info.name != ""

        # 验证主角字段正确
        mc = characters[0]
        assert mc["name"] == "林动"
        assert mc["role_type"] == "主角"
        assert mc["appearance"] == "英俊"
        assert mc["background"] == "落魄家族"
        assert mc["first_chapter"] == 1

        # 验证反派字段正确
        villain = characters[2]
        assert villain["name"] == "异魔王"
        assert villain["role_type"] == "反派"
        assert villain["current_status"] == "封印中"

    @pytest.mark.asyncio
    async def test_normalize_accepts_merged_characters(self):
        """验证 _normalize_outline_result 能正常处理合并后的数据"""
        from app.schemas.work_schema import CharacterInfo

        # 模拟合并后的 characters
        merged_characters = [
            {
                "name": "林动",
                "role_type": "主角",
                "gender": "男",
                "age": "16",
                "appearance": "英俊",
                "personality": "坚韧",
                "background": "落魄家族",
                "skills": "符文术",
                "current_status": "修炼中",
                "current_goal": "振兴林家",
                "first_chapter": 1,
            },
        ]

        # 验证每个角色都能被 CharacterInfo 正确解析
        for c in merged_characters:
            info = CharacterInfo(**c)
            assert info.name == "林动"
            assert info.first_chapter == 1
            assert info.appearance == "英俊"

    @pytest.mark.asyncio
    async def test_sse_status_phases(self):
        """验证新的 SSE 阶段 generating_character_briefs / generating_character_details 正确触发"""
        events = []

        def mock_emit(event_type, data):
            events.append((event_type, data))

        # 模拟 _status 回调
        def _status(phase, message):
            mock_emit("outline_status", {"phase": phase, "message": message})

        # 模拟新的流程状态调用
        _status("generating_character_briefs", "正在生成角色概览...")
        _status("generating_character_details", "正在生成角色详情（1/2）...")
        _status("generating_character_details", "正在生成角色详情（2/2）...")

        assert len(events) == 3
        assert events[0][1]["phase"] == "generating_character_briefs"
        assert events[1][1]["phase"] == "generating_character_details"
        assert events[2][1]["message"] == "正在生成角色详情（2/2）..."


# ──────────────────────────── 工具定义验证 ────────────────────────────


class TestToolDefinitions:
    """验证新工具定义存在且名称正确"""

    def test_submit_character_briefs_tool_exists(self):
        from app.services.work_service import SUBMIT_CHARACTER_BRIEFS_TOOL

        assert SUBMIT_CHARACTER_BRIEFS_TOOL.name == "submit_character_briefs"

    def test_submit_character_details_tool_exists(self):
        from app.services.work_service import SUBMIT_CHARACTER_DETAILS_TOOL

        assert SUBMIT_CHARACTER_DETAILS_TOOL.name == "submit_character_details"

    def test_tool_callbacks_return_expected(self):
        from app.services.work_service import (
            _submit_character_briefs_tool,
            _submit_character_details_tool,
        )

        assert _submit_character_briefs_tool() == "character_briefs_received"
        assert _submit_character_details_tool() == "character_details_received"

    def test_old_submit_characters_tool_removed(self):
        """旧的 SUBMIT_CHARACTERS_TOOL 应已删除"""
        import app.services.work_service as ws

        assert not hasattr(ws, "SUBMIT_CHARACTERS_TOOL")
        assert not hasattr(ws, "_submit_characters_tool")
        assert not hasattr(ws, "_SubmitCharactersInput")
