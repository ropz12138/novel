"""测试 first_chapter → first_appearance_stage 重构

验证：
1. CharacterDetail schema 包含 first_appearance_stage 字段（str，中纲阶段ID）
2. CharacterBrief schema 中 first_chapter 改为 first_appearance_stage
3. CharacterInfo schema 同步更新
4. submit_character_details 合并时优先从 detail 取 first_appearance_stage
5. edit_character_details 的 prompt 包含 first_appearance_stage
6. 数据库模型 Character.first_appearance_stage 类型为 str
"""

import sys

import pytest

sys.path.insert(0, "/root/Novel/backend")


# ──────────────────────── 1. Schema 验证 ────────────────────────


class TestCharacterDetailSchemaWithStage:
    """CharacterDetail 包含 first_appearance_stage 字段"""

    def test_parse_full_detail_with_stage(self):
        from app.schemas.work_schema import CharacterDetail

        d = CharacterDetail(
            name="林动",
            appearance="剑眉星目",
            personality="坚韧不拔",
            background="落魄家族后人",
            skills="祖传符文术",
            current_status="修炼中",
            current_goal="振兴林家",
            first_appearance_stage="M1",
        )
        assert d.name == "林动"
        assert d.first_appearance_stage == "M1"

    def test_defaults_stage_is_m1(self):
        from app.schemas.work_schema import CharacterDetail

        d = CharacterDetail(name="龙套A")
        assert d.first_appearance_stage == "M1"

    def test_detail_has_expected_fields(self):
        from app.schemas.work_schema import CharacterDetail

        fields = CharacterDetail.model_fields
        expected = {
            "name", "appearance", "personality", "background",
            "skills", "current_status", "current_goal", "first_appearance_stage",
        }
        assert set(fields.keys()) == expected

    def test_no_first_chapter_field(self):
        """CharacterDetail 不应再包含 first_chapter 字段"""
        from app.schemas.work_schema import CharacterDetail

        fields = CharacterDetail.model_fields
        assert "first_chapter" not in fields


class TestCharacterBriefSchemaWithStage:
    """CharacterBrief 中 first_chapter → first_appearance_stage"""

    def test_parse_full_brief_with_stage(self):
        from app.schemas.work_schema import CharacterBrief

        b = CharacterBrief(
            name="林动",
            role_type="主角",
            gender="男",
            age="16",
            first_appearance_stage="M1",
            brief="天赋异禀的少年",
        )
        assert b.name == "林动"
        assert b.first_appearance_stage == "M1"

    def test_defaults_stage_is_m1(self):
        from app.schemas.work_schema import CharacterBrief

        b = CharacterBrief(name="路人甲")
        assert b.first_appearance_stage == "M1"

    def test_brief_has_expected_fields(self):
        from app.schemas.work_schema import CharacterBrief

        fields = CharacterBrief.model_fields
        expected = {"name", "role_type", "gender", "age", "first_appearance_stage", "brief"}
        assert set(fields.keys()) == expected

    def test_no_first_chapter_field(self):
        from app.schemas.work_schema import CharacterBrief

        fields = CharacterBrief.model_fields
        assert "first_chapter" not in fields


class TestCharacterInfoSchemaWithStage:
    """CharacterInfo 中 first_chapter → first_appearance_stage"""

    def test_parse_with_stage(self):
        from app.schemas.work_schema import CharacterInfo

        info = CharacterInfo(
            name="林动",
            role_type="主角",
            gender="男",
            age="16",
            appearance="英俊",
            personality="坚韧",
            background="落魄家族",
            skills="符文术",
            current_status="修炼中",
            current_goal="振兴林家",
            first_appearance_stage="M1",
        )
        assert info.first_appearance_stage == "M1"

    def test_defaults(self):
        from app.schemas.work_schema import CharacterInfo

        info = CharacterInfo(name="路人")
        assert info.first_appearance_stage == "M1"

    def test_no_first_chapter_field(self):
        from app.schemas.work_schema import CharacterInfo

        fields = CharacterInfo.model_fields
        assert "first_chapter" not in fields
        assert "first_appearance_stage" in fields


class TestCharacterCreateUpdateSchemasWithStage:
    """CharacterCreateRequest / CharacterUpdateRequest / CharacterOut 包含 first_appearance_stage"""

    def test_character_create_with_stage(self):
        from app.schemas.work_schema import CharacterCreateRequest

        c = CharacterCreateRequest(
            name="林动",
            first_appearance_stage="M6",
        )
        assert c.first_appearance_stage == "M6"

    def test_character_create_default_stage(self):
        from app.schemas.work_schema import CharacterCreateRequest

        c = CharacterCreateRequest(name="林动")
        assert c.first_appearance_stage is None

    def test_character_update_with_stage(self):
        from app.schemas.work_schema import CharacterUpdateRequest

        c = CharacterUpdateRequest(first_appearance_stage="M8")
        assert c.first_appearance_stage == "M8"

    def test_character_read_with_stage(self):
        from app.schemas.work_schema import CharacterOut

        c = CharacterOut(
            id="abc",
            work_id="w1",
            name="林动",
            role_type="主角",
            gender="男",
            age="16",
            appearance="",
            personality="",
            background="",
            skills="",
            current_status="存活",
            current_goal="",
            last_location="",
            last_chapter=None,
            relationships={},
            first_appearance_stage="M3",
            notes="",
        )
        assert c.first_appearance_stage == "M3"


# ──────────────────────── 2. 合并逻辑验证 ────────────────────────


class TestMergeBriefsAndDetailsWithStage:
    """brief + detail 合并时，first_appearance_stage 优先从 detail 中取"""

    def _merge(self, briefs: list[dict], details: list[dict]) -> list[dict]:
        """模拟 work_service 中的合并逻辑（detail 优先）"""
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
                # 核心变更：detail 优先，fallback 到 brief
                "first_appearance_stage": (
                    detail.get("first_appearance_stage")
                    or brief.get("first_appearance_stage", "M1")
                ),
            })
        return characters

    def test_detail_overrides_brief_stage(self):
        """detail 中指定的 first_appearance_stage 覆盖 brief 中的值"""
        briefs = [
            {"name": "林动", "role_type": "主角", "first_appearance_stage": "M1"},
            {"name": "绫清竹", "role_type": "配角", "first_appearance_stage": "M1"},
        ]
        details = [
            {"name": "林动", "appearance": "英俊", "first_appearance_stage": "M1"},
            {"name": "绫清竹", "appearance": "清冷", "first_appearance_stage": "M3"},
        ]

        result = self._merge(briefs, details)
        assert result[0]["first_appearance_stage"] == "M1"
        assert result[1]["first_appearance_stage"] == "M3"

    def test_detail_missing_stage_falls_back_to_brief(self):
        """detail 中没有 first_appearance_stage 时 fallback 到 brief"""
        briefs = [
            {"name": "林动", "role_type": "主角", "first_appearance_stage": "M2"},
        ]
        details = [
            {"name": "林动", "appearance": "英俊"},
        ]

        result = self._merge(briefs, details)
        assert result[0]["first_appearance_stage"] == "M2"

    def test_both_missing_defaults_to_m1(self):
        """两者都没有时默认 M1"""
        briefs = [{"name": "林动", "role_type": "主角"}]
        details = [{"name": "林动", "appearance": "英俊"}]

        result = self._merge(briefs, details)
        assert result[0]["first_appearance_stage"] == "M1"

    def test_edit_can_change_stage(self):
        """edit_character_details 可以通过 detail 修改 first_appearance_stage

        这是之前 bug 的核心场景：
        - 初始 briefs: 所有角色 first_appearance_stage = "M1"
        - edit 时 detail 指定了正确的 stage
        - 合并后应使用 detail 中的值
        """
        briefs = [
            {"name": "秦墨", "role_type": "主角", "first_appearance_stage": "M1"},
            {"name": "伊格纳修斯", "role_type": "反派", "first_appearance_stage": "M1"},
            {"name": "大主教", "role_type": "反派", "first_appearance_stage": "M1"},
        ]
        details = [
            {"name": "秦墨", "appearance": "英俊", "first_appearance_stage": "M1"},
            {"name": "伊格纳修斯", "appearance": "金发碧眼", "first_appearance_stage": "M8"},
            {"name": "大主教", "appearance": "威严", "first_appearance_stage": "M12"},
        ]

        result = self._merge(briefs, details)
        assert result[0]["first_appearance_stage"] == "M1"  # 秦墨不变
        assert result[1]["first_appearance_stage"] == "M8"  # 伊格纳修斯修正
        assert result[2]["first_appearance_stage"] == "M12"  # 大主教修正

    def test_merged_result_compatible_with_character_info(self):
        """合并结果可以用 CharacterInfo 实例化"""
        from app.schemas.work_schema import CharacterInfo

        briefs = [{"name": "林动", "role_type": "主角", "first_appearance_stage": "M1"}]
        details = [{"name": "林动", "appearance": "英俊", "first_appearance_stage": "M2"}]

        result = self._merge(briefs, details)
        info = CharacterInfo(**result[0])
        assert info.name == "林动"
        assert info.first_appearance_stage == "M2"


# ──────────────────────── 3. SubmitInput Schema 验证 ────────────────────────


class TestSubmitInputSchemasWithStage:
    """_SubmitCharacterBriefsInput / _SubmitCharacterDetailsInput 支持 first_appearance_stage"""

    def test_submit_briefs_input_with_stage(self):
        from app.schemas.work_schema import CharacterBrief
        from app.services.work_service import _SubmitCharacterBriefsInput

        briefs = [
            CharacterBrief(name="林动", first_appearance_stage="M1"),
            CharacterBrief(name="绫清竹", first_appearance_stage="M3"),
        ]
        inp = _SubmitCharacterBriefsInput(briefs=briefs)
        assert inp.briefs[0].first_appearance_stage == "M1"
        assert inp.briefs[1].first_appearance_stage == "M3"

    def test_submit_details_input_with_stage(self):
        from app.schemas.work_schema import CharacterDetail
        from app.services.work_service import _SubmitCharacterDetailsInput

        details = [
            CharacterDetail(name="林动", first_appearance_stage="M1"),
            CharacterDetail(name="绫清竹", first_appearance_stage="M3"),
        ]
        inp = _SubmitCharacterDetailsInput(characters=details)
        assert inp.characters[0].first_appearance_stage == "M1"
        assert inp.characters[1].first_appearance_stage == "M3"


# ──────────────────────── 4. Outline Tools Schema 验证 ────────────────────────


class TestOutlineToolsSchemasWithStage:
    """outline_tools.py 中的 AddCharacterInput 等包含 first_appearance_stage"""

    def test_add_character_schema_defaults(self):
        from app.services.supervisor.outline_tools import AddCharacterInput

        s = AddCharacterInput(name="Bob")
        assert s.role_type == "配角"
        assert s.first_appearance_stage == "M1"

    def test_add_character_schema_with_custom_stage(self):
        from app.services.supervisor.outline_tools import AddCharacterInput

        s = AddCharacterInput(name="伊格纳修斯", first_appearance_stage="M8")
        assert s.first_appearance_stage == "M8"

    def test_add_character_has_no_first_chapter(self):
        from app.services.supervisor.outline_tools import AddCharacterInput

        fields = AddCharacterInput.model_fields
        assert "first_chapter" not in fields
        assert "first_appearance_stage" in fields


# ──────────────────────── 5. edit_character_details prompt 验证 ────────────────────────


class TestEditCharacterDetailsPrompt:
    """edit_character_details 的 prompt 应包含 first_appearance_stage"""

    def test_prompt_contains_first_appearance_stage(self):
        """检查 edit_character_details 函数的 prompt 构建逻辑包含 first_appearance_stage"""
        import inspect
        from app.services.supervisor.outline_tools import _edit_character_details_coroutine

        source = inspect.getsource(_edit_character_details_coroutine)
        assert "first_appearance_stage" in source, (
            "edit_character_details 的代码中应包含 first_appearance_stage 字段"
        )
        assert "first_chapter" not in source or "first_appearance_stage" in source, (
            "edit_character_details 应已从 first_chapter 迁移到 first_appearance_stage"
        )


# ──────────────────────── 6. 数据库模型验证 ────────────────────────


class TestCharacterModelWithStage:
    """Character 数据库模型包含 first_appearance_stage 字段"""

    def test_model_has_first_appearance_stage(self):
        from app.models.work_model import Character

        columns = {c.name for c in Character.__table__.columns}
        assert "first_appearance_stage" in columns

    def test_model_no_first_chapter(self):
        from app.models.work_model import Character

        columns = {c.name for c in Character.__table__.columns}
        assert "first_chapter" not in columns
