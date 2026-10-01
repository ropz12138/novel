"""Supervisor 工作工具轮次上限：40 轮后收口，不把上限当错误抛给前端。"""

import asyncio
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from services.agents.supervisor_turn import (
    HIGH_SUPERVISOR_GRAPH_RECURSION_LIMIT,
    HIGH_SUPERVISOR_TOOL_CALL_LIMIT,
    RESPOND_TO_USER_TOOL,
    SUPERVISOR_GRAPH_RECURSION_LIMIT,
    SUPERVISOR_TOOL_LIMIT_INSTRUCTION,
    SUPERVISOR_TOOL_CALL_LIMIT,
    count_current_run_work_tool_calls,
    count_supervisor_work_tool_calls,
    get_supervisor_iteration_limits,
    prepare_supervisor_ai_message,
)


def test_tool_round_limit_is_forty():
    assert SUPERVISOR_TOOL_CALL_LIMIT == 40


def test_graph_recursion_limit_covers_forty_work_rounds_plus_wrap_up():
    assert SUPERVISOR_GRAPH_RECURSION_LIMIT >= SUPERVISOR_TOOL_CALL_LIMIT * 2 + 2


def test_high_review_intensity_uses_eighty_tools_and_two_hundred_graph_steps():
    assert HIGH_SUPERVISOR_TOOL_CALL_LIMIT == 80
    assert HIGH_SUPERVISOR_GRAPH_RECURSION_LIMIT == 200
    assert get_supervisor_iteration_limits("high") == (80, 200)


def test_low_and_medium_review_intensity_keep_default_limits():
    assert get_supervisor_iteration_limits("low") == (40, 90)
    assert get_supervisor_iteration_limits("medium") == (40, 90)


def test_count_work_rounds_ignores_respond_to_user_and_non_ai():
    messages = [
        SystemMessage(content="sys"),
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"id": "1", "name": "update_node", "args": {}}]),
        ToolMessage(content="ok", tool_call_id="1"),
        AIMessage(
            content="",
            tool_calls=[{"id": "2", "name": RESPOND_TO_USER_TOOL, "args": {"message": "好了"}}],
        ),
    ]
    assert count_supervisor_work_tool_calls(messages) == 1


def test_parallel_work_tools_each_consume_one_call():
    messages = [AIMessage(content="", tool_calls=[
        {"id": "1", "name": "read_node", "args": {}},
        {"id": "2", "name": "update_node", "args": {}},
        {"id": "3", "name": RESPOND_TO_USER_TOOL, "args": {"message": "忽略"}},
    ])]
    assert count_supervisor_work_tool_calls(messages) == 2


def test_count_work_rounds_reaches_forty():
    messages = []
    for i in range(40):
        messages.append(
            AIMessage(
                content="",
                tool_calls=[{"id": str(i), "name": "update_node", "args": {}}],
            )
        )
    assert count_supervisor_work_tool_calls(messages) == 40


def test_new_user_message_gets_a_fresh_forty_tool_round_budget():
    history = [
        AIMessage(
            content="",
            tool_calls=[{"id": f"old-{i}", "name": "update_node", "args": {}}],
        )
        for i in range(42)
    ]
    run_start_count = count_supervisor_work_tool_calls(history)
    current_messages = [*history, HumanMessage(content="继续执行")]

    assert count_current_run_work_tool_calls(current_messages, run_start_count) == 0

    for i in range(40):
        current_messages.append(AIMessage(
            content="",
            tool_calls=[{"id": f"new-{i}", "name": "update_node", "args": {}}],
        ))

    assert count_current_run_work_tool_calls(current_messages, run_start_count) == 40


def test_tool_limit_instruction_requires_respond_to_user():
    assert "respond_to_user" in SUPERVISOR_TOOL_LIMIT_INSTRUCTION
    assert "Do not call any other tool" in SUPERVISOR_TOOL_LIMIT_INSTRUCTION


def test_wrap_up_respond_to_user_still_ends_normally():
    msg = AIMessage(
        content="",
        tool_calls=[{
            "id": "c1",
            "name": RESPOND_TO_USER_TOOL,
            "args": {"message": "本轮工具次数已用尽。角色卡已改完，第三章尚未重写。"},
        }],
    )
    action, prepared = prepare_supervisor_ai_message(msg)
    assert action == "end"
    assert "角色卡已改完" in prepared.content
    assert not prepared.tool_calls


def test_graph_recursion_wraps_up_as_success(monkeypatch):
    from services.agents.supervisor import SupervisorAgent

    class FakeGraph:
        async def astream(self, *a, **k):
            raise GraphRecursionError("Recursion limit of 90 reached without hitting a stop condition")
            yield {}

    agent = SupervisorAgent()
    monkeypatch.setattr(agent, "_build_graph", lambda **kw: FakeGraph())
    monkeypatch.setattr(agent, "_load_model_pref", lambda user_id: {})
    monkeypatch.setattr(agent, "_load_chat_history", lambda sid: ([], []))
    monkeypatch.setattr(agent, "_build_system_prompt", lambda **kw: "sys")

    async def fake_wrap(messages, *, llm, emit=None):
        return AIMessage(content="本轮工具次数已用尽。角色卡已改完，第三章尚未重写。")

    monkeypatch.setattr(
        "services.agents.supervisor.wrap_up_supervisor_after_tool_limit",
        fake_wrap,
    )

    result = asyncio.run(agent.run("继续改第三章", {"session_id": None, "work_id": None}))
    assert result["success"] is True
    assert "本轮工具次数已用尽" in result["message"]
