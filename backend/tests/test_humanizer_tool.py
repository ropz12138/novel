"""自然化规则从技能入口完整读取，正文由 Supervisor 直接保存。"""
import asyncio
import json

from services.agents import supervisor as supervisor_mod
from services.agents.tools import workflow_skill_tools as workflow


def test_humanize_skill_returns_complete_rules_without_legacy_tool():
    tools = {tool.name for tool in supervisor_mod.SupervisorAgent()._get_tools()}
    assert "humanize_node_content" not in tools
    assert "load_workflow_skill" in tools
    assert "read_skill_reference" in tools
    loaded = json.loads(asyncio.run(workflow.load_workflow_skill.ainvoke({"skill_name": "humanize-fiction"})))
    assert loaded["success"]
    assert loaded["references"] == ["chapter_writer.txt", "fiction_humanizer.txt", "humanizer_agent.txt"]
    for name in loaded["references"]:
        reference = json.loads(asyncio.run(workflow.read_skill_reference.ainvoke({
            "skill_name": "humanize-fiction", "reference_name": name,
        })))
        source = (workflow.REFERENCE_ROOT / name).read_text(encoding="utf-8")
        assert reference["success"]
        assert reference["content"] == source


def test_agent_authored_content_uses_direct_save_path(monkeypatch):
    from services.agents.tools import node_tools

    def save(node_id, title, content, *args, **kwargs):
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
