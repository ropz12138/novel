"""模型请求跨存储重放保持前缀、消息边界与完整内容。"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from models.user import User
from services.agents.supervisor import SupervisorAgent
from services.llm.langchain_adapter import langchain_messages_to_dicts
from services.message_langchain import db_message_dicts_to_langchain
from services.session_history_page import list_history_page
from services.session_store import session_store


def _session(db):
    user = User(username="cache-test", email="cache@test.local", password_hash="x")
    db.add(user)
    db.commit()
    return session_store.create_session(user.id)["id"]


def test_assistant_roundtrip_keeps_boundaries_whitespace_and_reasoning(db_session):
    sid = _session(db_session)
    agent = SupervisorAgent()
    messages = [
        AIMessage(content="  正文\n", additional_kwargs={"reasoning_content": "思考\n"}, tool_calls=[
            {"id": "c1", "name": "read_node_content", "args": {"node_id": "n1"}},
            {"id": "c2", "name": "read_node_content", "args": {"node_id": "n2"}},
        ]),
        ToolMessage(content="全文一\n", tool_call_id="c1"),
        ToolMessage(content="全文二\n", tool_call_id="c2"),
        AIMessage(content="", additional_kwargs={"reasoning_content": "只有思考"}),
        AIMessage(content="\n 完成 \n"),
    ]
    agent._save_intermediate_messages(sid, messages[:1])
    agent._save_tool_results(sid, messages[1:3])
    agent._save_intermediate_messages(sid, messages[3:])
    restored = db_message_dicts_to_langchain(session_store.get_messages(sid))
    assert langchain_messages_to_dicts(restored) == langchain_messages_to_dicts(messages)
    page = list_history_page(sid)["messages"]
    assert all(m["role"] in {"assistant", "tool_call"} for m in page)
    assert [m["content"] for m in page if m["role"] == "tool_call"] == ["read_node_content"] * 2
    assert not any("model_message" in m["meta"] for m in page)


def test_adjacent_assistant_tool_calls_keep_separate_boundaries(db_session):
    sid = _session(db_session)
    messages = [AIMessage(content="", tool_calls=[{"id": key, "name": "lookup", "args": {}}]) for key in ["a", "b"]]
    SupervisorAgent()._save_intermediate_messages(sid, messages)
    restored = db_message_dicts_to_langchain(session_store.get_messages(sid))
    assert langchain_messages_to_dicts(restored) == langchain_messages_to_dicts(messages)


def test_dynamic_system_is_persisted_in_place_and_only_changes_when_needed(db_session):
    sid = _session(db_session)
    agent = SupervisorAgent()
    user1 = session_store.add_message(sid, "user", "第一轮")
    first = agent._assemble_initial_messages([], [HumanMessage(content="第一轮")],
        context_node_ids=["n1"], chapter_review_intensity="high", session_id=sid,
        before_message_id=user1["id"])
    assert first[1].content.startswith(agent._build_system_prompt())
    agent._save_intermediate_messages(sid, [AIMessage(content=" 完成 \n")])
    user2 = session_store.add_message(sid, "user", "第二轮")
    history, current = agent._load_chat_history(sid)
    second = agent._assemble_initial_messages(history, db_message_dicts_to_langchain(current),
        context_node_ids=["n1"], chapter_review_intensity="high", session_id=sid,
        before_message_id=user2["id"])
    assert langchain_messages_to_dicts(second[:len(first)]) == langchain_messages_to_dicts(first)
    assert len([m for m in session_store.get_messages(sid) if m["role"] == "system"]) == 1
    assert [m["role"] for m in session_store.get_messages(sid)][:2] == ["system", "user"]
    assert all(m["role"] != "system" for m in list_history_page(sid)["messages"])


def test_reset_dynamic_system_to_defaults_keeps_old_prompt_and_appends_full_default():
    agent = SupervisorAgent()
    first = agent._assemble_initial_messages([], [HumanMessage(content="第一轮")], chapter_review_intensity="high")
    history = first[1:] + [AIMessage(content="完成")]
    reset = agent._assemble_initial_messages(history, [HumanMessage(content="第二轮")])
    assert reset[:-2] == [first[0], *history]
    assert isinstance(reset[-2], SystemMessage)
    assert reset[-2].content == agent._build_system_prompt()
    repeated = agent._assemble_initial_messages(reset[1:] + [AIMessage(content="完成")], [HumanMessage(content="第三轮")])
    assert sum(isinstance(m, SystemMessage) for m in repeated) == 3


def test_legacy_history_still_loads_without_guessing_message_boundaries():
    rows = [
        {"role": "assistant", "content": "旧文本", "meta": {}},
        {"role": "tool_call", "content": "lookup", "meta": {"tool_call_id": "c", "args": {}}},
        {"role": "tool_result", "content": "结果", "meta": {"tool_call_id": "c"}},
    ]
    assert len(db_message_dicts_to_langchain(rows)) == 3


def test_interrupted_tool_calls_are_removed_from_model_history_too(db_session):
    sid = _session(db_session)
    agent = SupervisorAgent()
    agent._save_intermediate_messages(sid, [AIMessage(content="正在读取", tool_calls=[
        {"id": "done", "name": "lookup", "args": {}},
        {"id": "interrupted", "name": "lookup", "args": {}},
    ])])
    agent._save_tool_results(sid, [ToolMessage(content="完成", tool_call_id="done")])
    session_store.discard_unpaired_tool_calls(sid)
    restored = db_message_dicts_to_langchain(session_store.get_messages(sid))
    assert restored[0].content == "正在读取"
    assert [tc["id"] for tc in restored[0].tool_calls] == ["done"]
    assert restored[1].tool_call_id == "done"


def test_run_replays_persisted_prefix_after_process_restart(monkeypatch, db_session):
    import asyncio
    from langchain_core.messages import AIMessageChunk

    sid = _session(db_session)
    requests = []

    class LLM:
        async def astream(self, messages):
            requests.append(langchain_messages_to_dicts(messages))
            yield AIMessageChunk(content="  已完成。\n", additional_kwargs={"reasoning_content": "完整思考"})

    monkeypatch.setattr("services.agents.supervisor.get_llm", lambda **kw: LLM())
    monkeypatch.setattr("services.agents.supervisor.bind_tools_to_llm", lambda model, tools, **kw: model)
    for text in ["第一轮", "第二轮"]:
        session_store.add_message(sid, "user", text)
        result = asyncio.run(SupervisorAgent().run(text, {
            "session_id": sid, "context_node_ids": ["n1"], "chapter_review_intensity": "high",
        }))
        assert result["success"], result
    assert requests[1][:len(requests[0])] == requests[0]
    assert len([r for r in session_store.get_messages(sid) if r["role"] == "system"]) == 1
