"""小说自然化规则读取工具：完整返回规则，由 supervisor 自行编辑。"""
import asyncio
import json

from services.agents import llm as llm_mod
from services.agents import supervisor as supervisor_mod
from services.agents.tools import humanizer_tools as ht


def test_humanizer_returns_full_skill_without_llm_or_database(monkeypatch, tmp_path):
    import database

    def unexpected(*args, **kwargs):
        raise AssertionError("读取规则时不应调用 LLM 或数据库")

    monkeypatch.setattr(llm_mod, "get_llm", unexpected)
    monkeypatch.setattr(database, "SessionLocal", unexpected)
    text = "规则开头\n" + "完整规则内容。\n" * 2000 + "规则结尾\n"
    path = tmp_path / "fiction_humanizer.txt"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(ht, "PROMPT_PATH", path)

    result = json.loads(asyncio.run(ht._humanize_node_content_async("chapter-id", "用户要求自然化")))

    assert result["success"] is True
    assert result["status"] == "skill_loaded"
    assert result["changed"] is False
    assert result["node_id"] == "chapter-id"
    assert result["reason"] == "用户要求自然化"
    assert result["skill_content"] == text
    assert "diff" not in result
    assert "issue_count" not in result
    assert path.read_text(encoding="utf-8") == text


def test_humanizer_missing_skill_reports_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(ht, "PROMPT_PATH", tmp_path / "missing.txt")
    result = json.loads(asyncio.run(ht._humanize_node_content_async("chapter-id")))
    assert result["success"] is False
    assert "读取小说自然化规则失败" in result["error"]
    assert "skill_content" not in result


def test_humanizer_registered_tool_preserves_inputs():
    tools = supervisor_mod.SupervisorAgent()._get_tools()
    assert "humanize_node_content" in {tool.name for tool in tools}
    assert set(ht.HumanizeNodeContentInput.model_fields) == {"node_id", "reason"}
    result = json.loads(asyncio.run(ht.humanize_node_content.ainvoke({"node_id": "chapter-id"})))
    assert result["status"] == "skill_loaded"
    assert result["skill_content"] == ht.PROMPT_PATH.read_text(encoding="utf-8")


def test_agent_authored_content_uses_direct_save_path(monkeypatch):
    from services.agents.tools import node_tools

    def save(node_id, title, content, *args):
        assert node_id == "chapter-id"
        assert content == "原段开头。改写后的句子。原段结尾。"
        return json.dumps({"success": True, "node_id": node_id})

    monkeypatch.setattr(node_tools, "_update_node_sync", save)
    monkeypatch.setattr(node_tools, "_get_emit", lambda: None)
    result = json.loads(asyncio.run(node_tools._update_node_async(
        node_id="chapter-id", content="原段开头。改写后的句子。原段结尾。",
        reason="根据自然化规则完成修改",
    )))
    assert result["success"] is True
