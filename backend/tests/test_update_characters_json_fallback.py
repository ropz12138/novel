"""测试 update_characters_after_chapter 工具的 JSON 纯文本解析模式

验证：不使用 with_structured_output，改为纯文本 prompt + JSON 解析，
兼容不支持 response_format 的 LLM 提供商（如 DeepSeek）。
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage


# ── Helpers ──


def _mock_character(name, role_type="主角", status="正常", goal="未知", location="未知"):
    c = MagicMock()
    c.name = name
    c.role_type = role_type
    c.current_status = status
    c.current_goal = goal
    c.last_location = location
    c.last_chapter = 0
    return c


def _mock_db_with_characters(*characters):
    db = MagicMock()
    char_query = MagicMock()
    char_query.filter_by.return_value.all.return_value = list(characters)

    def query_side_effect(model):
        return char_query

    db.query.side_effect = query_side_effect
    return db


def _make_chain_mock(ai_content):
    """创建一个模拟 prompt | llm 链的 mock，ainvoke 返回 AIMessage"""
    mock_chain = AsyncMock()
    mock_chain.ainvoke.return_value = AIMessage(content=ai_content)
    return mock_chain


# ── Tests ──


class TestUpdateCharactersJsonParsing:
    """验证 update_characters_after_chapter 通过纯文本 JSON 解析工作"""

    @pytest.mark.asyncio
    async def test_parses_json_output_correctly(self):
        """LLM 返回合法 JSON 文本时，正确解析并更新角色"""
        from app.services.agent.chapter_tools import _update_characters_after_chapter_coroutine

        char1 = _mock_character("林风", "主角", "修炼中", "突破", "山洞")
        db = _mock_db_with_characters(char1)

        json_response = json.dumps({
            "character_updates": [
                {"name": "林风", "current_status": "突破成功", "current_goal": "复仇", "last_location": "山洞深处"}
            ]
        })
        mock_chain = _make_chain_mock(json_response)

        with patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt:
            mock_pt.from_template.return_value.__or__.return_value = mock_chain

            config = {"configurable": {"db": db, "db_lock": MagicMock()}}
            result = await _update_characters_after_chapter_coroutine(
                chapter_number=1,
                chapter_content="林风在山洞中修炼，终于突破了瓶颈...",
                config=config,
                work_id="w1",
            )

        assert "1" in result or "林风" in result
        assert char1.current_status == "突破成功"
        assert char1.current_goal == "复仇"
        assert char1.last_location == "山洞深处"

    @pytest.mark.asyncio
    async def test_handles_empty_updates(self):
        """LLM 返回空更新列表时，不报错"""
        from app.services.agent.chapter_tools import _update_characters_after_chapter_coroutine

        char1 = _mock_character("路人甲", "配角")
        db = _mock_db_with_characters(char1)

        json_response = json.dumps({"character_updates": []})
        mock_chain = _make_chain_mock(json_response)

        with patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt:
            mock_pt.from_template.return_value.__or__.return_value = mock_chain

            config = {"configurable": {"db": db, "db_lock": MagicMock()}}
            result = await _update_characters_after_chapter_coroutine(
                chapter_number=1,
                chapter_content="路人甲在路边经过...",
                config=config,
                work_id="w1",
            )

        assert "无需更新" in result

    @pytest.mark.asyncio
    async def test_handles_json_with_markdown_fences(self):
        """LLM 返回带 markdown 代码块的 JSON 时，能正确提取"""
        from app.services.agent.chapter_tools import _update_characters_after_chapter_coroutine

        char1 = _mock_character("林风")
        db = _mock_db_with_characters(char1)

        fenced_response = '```json\n{"character_updates": [{"name": "林风", "current_status": "受伤", "current_goal": "", "last_location": ""}]}\n```'
        mock_chain = _make_chain_mock(fenced_response)

        with patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt:
            mock_pt.from_template.return_value.__or__.return_value = mock_chain

            config = {"configurable": {"db": db, "db_lock": MagicMock()}}
            await _update_characters_after_chapter_coroutine(
                chapter_number=1,
                chapter_content="林风被袭击了...",
                config=config,
                work_id="w1",
            )

        assert char1.current_status == "受伤"

    @pytest.mark.asyncio
    async def test_handles_malformed_json_gracefully(self):
        """LLM 返回无法解析的内容时，不崩溃，返回友好错误"""
        from app.services.agent.chapter_tools import _update_characters_after_chapter_coroutine

        char1 = _mock_character("林风")
        db = _mock_db_with_characters(char1)
        mock_chain = _make_chain_mock("这不是JSON格式的内容")

        with patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt:
            mock_pt.from_template.return_value.__or__.return_value = mock_chain

            config = {"configurable": {"db": db, "db_lock": MagicMock()}}
            result = await _update_characters_after_chapter_coroutine(
                chapter_number=1,
                chapter_content="...",
                config=config,
                work_id="w1",
            )

        assert isinstance(result, str)
        assert "跳过" in result

    @pytest.mark.asyncio
    async def test_skips_unknown_character_names(self):
        """LLM 返回了不存在的角色名时，跳过该角色不报错"""
        from app.services.agent.chapter_tools import _update_characters_after_chapter_coroutine

        char1 = _mock_character("林风")
        db = _mock_db_with_characters(char1)

        json_response = json.dumps({
            "character_updates": [
                {"name": "不存在的人", "current_status": "更新", "current_goal": "", "last_location": ""},
                {"name": "林风", "current_status": "升级", "current_goal": "", "last_location": ""},
            ]
        })
        mock_chain = _make_chain_mock(json_response)

        with patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt:
            mock_pt.from_template.return_value.__or__.return_value = mock_chain

            config = {"configurable": {"db": db, "db_lock": MagicMock()}}
            await _update_characters_after_chapter_coroutine(
                chapter_number=1,
                chapter_content="...",
                config=config,
                work_id="w1",
            )

        assert char1.current_status == "升级"

    @pytest.mark.asyncio
    async def test_non_dict_update_items_are_ignored(self):
        """character_updates 中混入 bool/null 时不应触发 .get 异常。"""
        from app.services.agent.chapter_tools import _update_characters_after_chapter_coroutine

        char1 = _mock_character("林风", "主角")
        db = _mock_db_with_characters(char1)

        json_response = json.dumps({
            "character_updates": [
                True,
                None,
                {"name": "林风", "current_status": "稳定", "current_goal": "", "last_location": ""}
            ]
        })
        mock_chain = _make_chain_mock(json_response)

        with patch("app.services.agent.chapter_tools.PromptTemplate") as mock_pt:
            mock_pt.from_template.return_value.__or__.return_value = mock_chain

            config = {"configurable": {"db": db, "db_lock": MagicMock()}}
            result = await _update_characters_after_chapter_coroutine(
                chapter_number=1,
                chapter_content="林风暂时稳定下来。",
                config=config,
                work_id="w1",
            )

        assert "林风" in result
        assert char1.current_status == "稳定"

    @pytest.mark.asyncio
    async def test_no_characters_returns_early(self):
        """没有角色时直接返回，不调用 LLM"""
        from app.services.agent.chapter_tools import _update_characters_after_chapter_coroutine

        db = MagicMock()
        query_mock = MagicMock()
        query_mock.filter_by.return_value.all.return_value = []
        db.query.return_value = query_mock

        config = {"configurable": {"db": db, "db_lock": MagicMock()}}
        result = await _update_characters_after_chapter_coroutine(
            chapter_number=1,
            chapter_content="...",
            config=config,
            work_id="w1",
        )

        assert "无角色" in result

    @pytest.mark.asyncio
    async def test_does_not_use_with_structured_output(self):
        """确认代码中不再出现 with_structured_output 调用"""
        import inspect
        from app.services.agent.chapter_tools import _update_characters_after_chapter_coroutine

        source = inspect.getsource(_update_characters_after_chapter_coroutine)
        assert "with_structured_output" not in source
