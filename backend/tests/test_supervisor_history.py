"""supervisor 多轮历史注入测试 — TDD。

_load_chat_history 把 session 历史（含 tool_call / tool_result）转成 langchain 消息，
排除当前轮 user（避免与 run 的 HumanMessage 重复）。
"""
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from services.agents.supervisor import SupervisorAgent
from services import session_store as ss_module


def test_load_chat_history_excludes_current_user(monkeypatch):
    fake = [
        {"role": "user", "content": "把主角改成学生", "meta": {}, "sort_order": 0},
        {"role": "assistant", "content": "已完成主角身份修改。是否需要重新生成第一章？", "meta": {}, "sort_order": 1},
        {"role": "user", "content": "需要", "meta": {}, "sort_order": 2},
    ]
    monkeypatch.setattr(ss_module.session_store, "get_messages", lambda sid: fake)

    agent = SupervisorAgent()
    history, current_turn = agent._load_chat_history("s1")

    assert len(history) == 2
    assert isinstance(history[0], HumanMessage)
    assert history[0].content == "把主角改成学生"
    assert isinstance(history[1], AIMessage)
    assert history[1].content.startswith("已完成主角身份修改")
    # 当前轮 user 被分离出来
    assert len(current_turn) == 1
    assert current_turn[0]["content"] == "需要"


def test_load_chat_history_empty_when_no_session():
    agent = SupervisorAgent()
    assert agent._load_chat_history(None) == ([], [])


def test_load_chat_history_includes_tool_chain(monkeypatch):
    fake = [
        {"role": "user", "content": "你好", "meta": {}, "sort_order": 0},
        {
            "role": "tool_call",
            "content": "get_canvas_index",
            "meta": {"args": {}, "tool_call_id": "call_1"},
            "sort_order": 1,
        },
        {
            "role": "tool_result",
            "content": '{"ok": true}',
            "meta": {"tool_call_id": "call_1", "tool_name": "get_canvas_index"},
            "sort_order": 2,
        },
        {"role": "assistant", "content": "你好！", "meta": {}, "sort_order": 3},
        {"role": "user", "content": "继续", "meta": {}, "sort_order": 4},
    ]
    monkeypatch.setattr(ss_module.session_store, "get_messages", lambda sid: fake)

    agent = SupervisorAgent()
    history, _ = agent._load_chat_history("s1")

    assert len(history) == 4
    assert isinstance(history[1], AIMessage)
    assert history[1].tool_calls[0]["name"] == "get_canvas_index"
    assert isinstance(history[2], ToolMessage)
    assert isinstance(history[3], AIMessage)
