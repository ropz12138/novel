"""Supervisor：每轮必须调工具，仅 respond_to_user 作为用户可见终态。"""

from langchain_core.messages import AIMessage, ToolMessage

from services.agents.supervisor_turn import (
    MAX_SUPERVISOR_TURN_RETRIES,
    RESPOND_TO_USER_TOOL,
    prepare_supervisor_ai_message,
    terminal_respond_to_user_message,
)
from services.llm.llm_service import resolve_anthropic_tool_choice, resolve_openai_tool_choice


def test_only_respond_to_user_becomes_final_text():
    msg = AIMessage(
        content="内部独白",
        tool_calls=[{
            "id": "c1",
            "name": RESPOND_TO_USER_TOOL,
            "args": {"message": "角色卡已更新，在侧栏查看。"},
        }],
    )
    action, prepared = prepare_supervisor_ai_message(msg)
    assert action == "end"
    assert not prepared.tool_calls
    assert prepared.content == "角色卡已更新，在侧栏查看。"


def test_successful_terminal_tool_uses_its_argument_as_final_text():
    messages = [
        AIMessage(
            content="内部独白",
            tool_calls=[{
                "id": "c1",
                "name": RESPOND_TO_USER_TOOL,
                "args": {"message": "完整的最终答复。"},
            }],
        ),
        ToolMessage(
            content='{"success": true, "message": "完整的最终答复。"}',
            tool_call_id="c1",
            name=RESPOND_TO_USER_TOOL,
        ),
    ]

    prepared = terminal_respond_to_user_message(messages)

    assert prepared is not None
    assert prepared.content == "完整的最终答复。"
    assert prepared.tool_calls == []


def test_work_tools_drop_respond_to_user_and_continue():
    msg = AIMessage(
        content="",
        tool_calls=[
            {"id": "c1", "name": "update_node", "args": {"node_id": "n1"}},
            {"id": "c2", "name": RESPOND_TO_USER_TOOL, "args": {"message": "改好了"}},
        ],
    )
    action, prepared = prepare_supervisor_ai_message(msg)
    assert action == "tools"
    assert [tc["name"] for tc in prepared.tool_calls] == ["update_node"]


def test_missing_tool_calls_must_retry():
    action, prepared = prepare_supervisor_ai_message(AIMessage(content="让我修改："))
    assert action == "retry"
    assert prepared.content == "让我修改："


def test_complete_content_without_tools_must_retry_with_respond_to_user():
    action, prepared = prepare_supervisor_ai_message(
        AIMessage(content="角色卡已更新，在侧栏查看。")
    )
    assert action == "retry"
    assert prepared.content == "角色卡已更新，在侧栏查看。"


def test_announcement_in_respond_to_user_must_retry():
    msg = AIMessage(
        content="",
        tool_calls=[{
            "id": "c1",
            "name": RESPOND_TO_USER_TOOL,
            "args": {"message": "明白了！让我先更新角色设定，然后重写第二章："},
        }],
    )
    action, _ = prepare_supervisor_ai_message(msg)
    assert action == "retry"


def test_empty_respond_to_user_message_must_retry():
    msg = AIMessage(
        content="",
        tool_calls=[{"id": "c1", "name": RESPOND_TO_USER_TOOL, "args": {"message": "  "}}],
    )
    action, _ = prepare_supervisor_ai_message(msg)
    assert action == "retry"


def test_retry_cap_is_two():
    assert MAX_SUPERVISOR_TURN_RETRIES == 2


def test_openai_and_anthropic_required_tool_choice():
    assert resolve_openai_tool_choice("required") == "required"
    assert resolve_anthropic_tool_choice("required") == {"type": "any"}
    assert resolve_anthropic_tool_choice("auto") == {"type": "auto"}
    assert resolve_anthropic_tool_choice("update_node") == {"type": "tool", "name": "update_node"}


def test_supervisor_bind_tools_does_not_force_required(monkeypatch):
    captured = {}
    monkeypatch.setattr("services.agents.llm.get_deep_agent_model", lambda **kwargs: object())
    def fake_build(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr("services.agents.deep_agent_runtime.build_deep_agent", fake_build)
    from services.agents.supervisor import SupervisorAgent
    SupervisorAgent()._build_graph()
    assert captured
    assert RESPOND_TO_USER_TOOL in [tool.name for tool in captured["tools"]]
    assert captured["completion_tool_name"] == RESPOND_TO_USER_TOOL


def test_respond_to_user_is_a_direct_terminal_tool():
    from services.agents.tools.respond_to_user_tool import respond_to_user

    assert respond_to_user.return_direct is True


def test_wrap_up_bind_tools_does_not_force_required():
    import inspect
    from services.agents.supervisor import wrap_up_supervisor_after_tool_limit
    assert 'tool_choice="required"' not in inspect.getsource(wrap_up_supervisor_after_tool_limit)


def test_supervisor_graph_uses_raised_recursion_limit():
    import inspect
    from services.agents import supervisor as supervisor_mod
    from services.agents.supervisor_turn import SUPERVISOR_GRAPH_RECURSION_LIMIT
    source = inspect.getsource(supervisor_mod.SupervisorAgent.run)
    assert "get_supervisor_iteration_limits" in source
    assert '"recursion_limit": graph_recursion_limit' in source
    assert SUPERVISOR_GRAPH_RECURSION_LIMIT == 90
