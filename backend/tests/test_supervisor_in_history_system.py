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
    assert "humanize-fiction" in prompt
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
    assert "专项文学评审在用户明确要求时执行" in text


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
    assert "每个评审视角检查一次" in messages[0].content
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


def test_assemble_injects_complete_notes_after_history_before_current_turn():
    agent = SupervisorAgent()
    complete_notes = "## 作品笔记（自动注入）\n\n" + ("完整内容" * 4000)
    history = [HumanMessage(content="旧问"), AIMessage(content="旧答")]

    messages = agent._assemble_initial_messages(
        history,
        [HumanMessage(content="新问")],
        note_context=complete_notes,
    )

    assert messages[0].content == agent._build_system_prompt()
    assert messages[1:3] == history
    assert isinstance(messages[3], SystemMessage)
    assert messages[3].additional_kwargs["type"] == "injected_work_notes"
    assert messages[3].content == complete_notes
    assert messages[4].content == "新问"


def test_assemble_places_notes_before_other_turn_specific_system_context():
    messages = SupervisorAgent()._assemble_initial_messages(
        [HumanMessage(content="旧问")],
        [HumanMessage(content="新问")],
        note_context="最新笔记",
        context_node_ids=["node-1"],
    )

    assert messages[2].additional_kwargs["type"] == "injected_work_notes"
    assert messages[2].content == "最新笔记"
    assert messages[3].additional_kwargs["type"] == "system_prompt_update"
    assert messages[4].content == "新问"


def test_assemble_reuses_unchanged_note_version_from_history():
    note_message = SystemMessage(
        content="同一版笔记",
        additional_kwargs={"type": "injected_work_notes"},
    )
    history = [HumanMessage(content="旧问"), note_message, AIMessage(content="旧答")]

    messages = SupervisorAgent()._assemble_initial_messages(
        history,
        [HumanMessage(content="新问")],
        note_context="同一版笔记",
    )

    assert messages.count(note_message) == 1
    assert messages[-1].content == "新问"


def test_assemble_appends_changed_note_version_after_complete_history():
    history = [
        SystemMessage(content="旧版笔记", additional_kwargs={"type": "injected_work_notes"}),
        HumanMessage(content="旧问"),
        AIMessage(content="旧答"),
    ]

    messages = SupervisorAgent()._assemble_initial_messages(
        history,
        [HumanMessage(content="新问")],
        note_context="新版笔记",
    )

    assert messages[:4] == [SystemMessage(content=SupervisorAgent()._build_system_prompt()), *history]
    assert messages[4].content == "新版笔记"
    assert messages[5].content == "新问"
