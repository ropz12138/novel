"""DeepSeek in-history system：头部 system A 稳定，轮次差异追加在历史之后。"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from services.agents.supervisor import SupervisorAgent


def test_stable_system_prompt_is_identical_across_calls():
    agent = SupervisorAgent()
    assert agent._build_system_prompt() == agent._build_system_prompt()


def test_stable_system_prompt_omits_turn_specific_fields():
    prompt = SupervisorAgent()._build_system_prompt()
    assert "## 用户指定的对话上下文" not in prompt
    assert "本次章节评审强度为中" in prompt
    assert "humanize_chapter_draft" in prompt
    assert "本次章节评审强度为高" not in prompt
    assert "本次章节评审强度为低" not in prompt


def test_in_history_system_none_on_default_medium_without_context_nodes():
    agent = SupervisorAgent()
    assert agent._build_in_history_system_prompt() is None
    assert agent._build_in_history_system_prompt(context_node_ids=None) is None
    assert agent._build_in_history_system_prompt(context_node_ids=[]) is None
    assert agent._build_in_history_system_prompt(chapter_review_intensity="medium") is None


def test_in_history_system_includes_context_node_ids():
    text = SupervisorAgent()._build_in_history_system_prompt(
        context_node_ids=["id-aaa", "id-bbb"],
    )
    assert "## 用户指定的对话上下文" in text
    assert "id-aaa" in text
    assert "id-bbb" in text
    assert "read_node_content" in text


def test_in_history_system_includes_low_review_intensity():
    text = SupervisorAgent()._build_in_history_system_prompt(
        chapter_review_intensity="low",
    )
    assert "本次章节评审强度为低" in text
    assert "不调用任何评审工具" in text


def test_assemble_appends_in_history_system_after_history_before_new_user():
    agent = SupervisorAgent()
    history = [HumanMessage(content="旧问"), AIMessage(content="旧答")]
    current_turn = [HumanMessage(content="新问")]
    messages = agent._assemble_initial_messages(
        history,
        current_turn,
        context_node_ids=["node-1"],
        chapter_review_intensity="medium",
    )

    assert isinstance(messages[0], SystemMessage)
    assert "node-1" not in messages[0].content
    assert "每个评审工具最多调用一次" in messages[0].content
    assert [type(m) for m in messages] == [
        SystemMessage,
        HumanMessage,
        AIMessage,
        SystemMessage,
        HumanMessage,
    ]
    assert "node-1" in messages[3].content
    assert messages[3].content.startswith(agent._build_system_prompt())
    assert messages[4].content == "新问"


def test_assemble_skips_in_history_system_when_only_default_medium():
    agent = SupervisorAgent()
    messages = agent._assemble_initial_messages(
        [HumanMessage(content="旧问")],
        [HumanMessage(content="新问")],
        context_node_ids=None,
        chapter_review_intensity="medium",
    )
    assert [type(m) for m in messages] == [SystemMessage, HumanMessage, HumanMessage]
    assert messages[1].content == "旧问"
    assert messages[2].content == "新问"
