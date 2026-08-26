"""Supervisor 中间过程持久化测试。"""
from langchain_core.messages import AIMessage, ToolMessage

from services.agents.supervisor import SupervisorAgent


def test_save_intermediate_persists_text_before_tool_call(monkeypatch):
    saved = []

    def fake_add(session_id, role, content, meta=None, work_id=None):
        saved.append({"role": role, "content": content, "meta": meta or {}})

    monkeypatch.setattr(
        "services.session_store.session_store.add_message",
        fake_add,
    )

    agent = SupervisorAgent()
    msg = AIMessage(content=[
        {"type": "text", "text": "让我先查看一下画布的当前状态："},
        {
            "type": "tool_call",
            "id": "call_abc",
            "name": "get_canvas_index",
            "args": {"reason": "查看画布"},
        },
    ])
    agent._save_intermediate_messages("sess-1", [msg], work_id="w1")

    assistant_msgs = [m for m in saved if m["role"] == "assistant"]
    tool_msgs = [m for m in saved if m["role"] == "tool_call"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == "让我先查看一下画布的当前状态："
    assert assistant_msgs[0]["meta"].get("phase") == "intermediate"
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"] == "get_canvas_index"


def test_save_intermediate_persists_tool_result(monkeypatch):
    saved = []

    def fake_add(session_id, role, content, meta=None, work_id=None):
        saved.append({"role": role, "content": content, "meta": meta or {}})

    monkeypatch.setattr(
        "services.session_store.session_store.add_message",
        fake_add,
    )

    agent = SupervisorAgent()
    agent._save_tool_results(
        "sess-1",
        [ToolMessage(content='{"ok": true}', tool_call_id="call_abc", name="get_canvas_index")],
        work_id="w1",
    )

    tool_results = [m for m in saved if m["role"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["content"] == '{"ok": true}'
    assert tool_results[0]["meta"]["tool_call_id"] == "call_abc"


def test_save_intermediate_tool_call_success_from_paired_result(monkeypatch):
    saved = []

    def fake_add(session_id, role, content, meta=None, work_id=None):
        saved.append({"role": role, "content": content, "meta": meta or {}})

    monkeypatch.setattr(
        "services.session_store.session_store.add_message",
        fake_add,
    )

    agent = SupervisorAgent()
    ai = AIMessage(
        content="",
        tool_calls=[{"id": "call_abc", "name": "get_canvas_index", "args": {}}],
    )
    tool_ok = ToolMessage(content='{"ok": true}', tool_call_id="call_abc", name="get_canvas_index")
    tool_fail = ToolMessage(content='{"error": "bad"}', tool_call_id="call_xyz", name="bad_tool")

    agent._save_intermediate_messages("sess-1", [ai, tool_ok], work_id="w1")
    ok_calls = [m for m in saved if m["role"] == "tool_call"]
    assert len(ok_calls) == 1
    assert ok_calls[0]["meta"]["success"] is True

    saved.clear()
    ai2 = AIMessage(
        content="",
        tool_calls=[{"id": "call_xyz", "name": "bad_tool", "args": {}}],
    )
    agent._save_intermediate_messages("sess-1", [ai2, tool_fail], work_id="w1")
    fail_calls = [m for m in saved if m["role"] == "tool_call"]
    assert len(fail_calls) == 1
    assert fail_calls[0]["meta"]["success"] is False


def test_save_intermediate_persists_final_text_only(monkeypatch):
    saved = []

    def fake_add(session_id, role, content, meta=None, work_id=None):
        saved.append({"role": role, "content": content, "meta": meta or {}})

    monkeypatch.setattr(
        "services.session_store.session_store.add_message",
        fake_add,
    )

    agent = SupervisorAgent()
    agent._save_intermediate_messages(
        "sess-1",
        [AIMessage(content="这是最终回复。")],
        work_id="w1",
    )

    assistant_msgs = [m for m in saved if m["role"] == "assistant"]
    assert len(assistant_msgs) == 1
    assert assistant_msgs[0]["content"] == "这是最终回复。"
    assert assistant_msgs[0]["meta"].get("phase") == "final"
