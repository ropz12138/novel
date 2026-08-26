"""对话上下文节点注入测试 — TDD。

用户在前端把若干节点加入对话上下文 → 前端发 context_node_ids →
supervisor 把 ids 注入 system_prompt，提示 agent 用 read_node_content 读取参考。
"""
from services.agents.supervisor import SupervisorAgent


def test_prompt_includes_context_node_ids_when_provided():
    agent = SupervisorAgent()
    prompt = agent._build_system_prompt(
        context_node_ids=["id-aaa", "id-bbb"],
    )
    assert "## 用户指定的对话上下文" in prompt
    assert "id-aaa" in prompt
    assert "id-bbb" in prompt
    assert "read_node_content" in prompt  # 提示 agent 用查询工具读取


def test_prompt_omits_context_section_when_empty():
    agent = SupervisorAgent()
    prompt = agent._build_system_prompt(context_node_ids=None)
    assert "## 用户指定的对话上下文" not in prompt


def test_prompt_omits_context_section_when_empty_list():
    agent = SupervisorAgent()
    prompt = agent._build_system_prompt(context_node_ids=[])
    assert "## 用户指定的对话上下文" not in prompt
