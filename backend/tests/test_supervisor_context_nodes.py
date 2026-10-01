"""对话上下文节点注入测试 — TDD。

用户在前端把若干节点加入对话上下文 → 前端发 context_node_ids →
supervisor 把 ids 作为 in-history system 追加，提示 agent 用 read_node_content 读取参考。
头部 system A 不含这些节点 id。
"""
from services.agents.supervisor import SupervisorAgent
from services.agents import supervisor as supervisor_mod


def test_prompt_includes_context_node_ids_when_provided():
    agent = SupervisorAgent()
    prompt = agent._build_in_history_system_prompt(
        context_node_ids=["id-aaa", "id-bbb"],
    )
    assert "## 用户指定的对话上下文" in prompt
    assert "id-aaa" in prompt
    assert "id-bbb" in prompt
    assert "read_node_content" in prompt  # 提示 agent 用查询工具读取


def test_prompt_omits_context_section_when_empty():
    agent = SupervisorAgent()
    assert agent._build_in_history_system_prompt(context_node_ids=None) is None
    prompt = agent._build_system_prompt()
    assert "## 用户指定的对话上下文" not in prompt


def test_prompt_omits_context_section_when_empty_list():
    agent = SupervisorAgent()
    assert agent._build_in_history_system_prompt(context_node_ids=[]) is None
    prompt = agent._build_system_prompt()
    assert "## 用户指定的对话上下文" not in prompt


def test_system_prompt_only_interpolates_context_placeholder(tmp_path, monkeypatch):
    template = '前文\n{context_section}JSON 示例：{"id": "角色UUID"}\n后文'
    (tmp_path / "supervisor_system.txt").write_text(template, encoding="utf-8")
    monkeypatch.setattr(supervisor_mod, "PROMPT_DIR", tmp_path)

    prompt = SupervisorAgent()._build_system_prompt()

    assert '{"id": "角色UUID"}' in prompt
    assert "node-1" not in prompt
    assert "{context_section}" not in prompt
