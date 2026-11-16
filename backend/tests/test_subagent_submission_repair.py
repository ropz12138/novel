"""一次任务提交及有限工具纠错；成功后立即结束。"""
import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from services.agents.subagent_runtime import invoke_isolated_subagent
from services.agents.supervisor import get_context, reset_context, set_context


class Submission(BaseModel):
    value: str


class Model:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.seen = []
        self.contexts = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    async def ainvoke(self, messages, config=None):
        self.seen.append(list(messages))
        self.contexts.append(dict(get_context()))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def call(value, call_id="submit", name="submit_test"):
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": {"value": value}}])


def run(monkeypatch, responses, handler):
    model = Model(responses)
    monkeypatch.setattr("services.agents.llm.get_deep_agent_model", lambda **kw: model)
    tool = StructuredTool.from_function(coroutine=handler, name="submit_test",
                                        description="提交", args_schema=Submission, return_direct=True)
    task = {"operation": "revise", "target": {"content": "全文" * 4000},
            "brief": "只改指定段落"}
    result = asyncio.run(invoke_isolated_subagent(
        name="writer", system_prompt="完整规则", task=task, tools=[tool]))
    return result, model, task


def test_tool_error_is_fed_back_in_same_isolated_task(monkeypatch):
    async def submit(value):
        if value == "bad":
            raise ValueError("old 在正文中未找到")
        return "提交成功"

    token = set_context({"user_id": "u", "work_id": "w", "history": "父会话秘密"})
    parent = get_context()
    try:
        result, model, task = run(monkeypatch, [call("bad", "first"), call("good", "second")], submit)
        assert len(model.seen) == 2
        assert model.seen[0][0].content == "完整规则"
        assert json.loads(model.seen[1][1].content) == task
        feedback = model.seen[1][-1]
        assert isinstance(feedback, ToolMessage)
        assert feedback.tool_call_id == "first" and feedback.status == "error"
        assert "old 在正文中未找到" in feedback.content
        assert result["messages"][-1].status == "success"
        assert all("history" not in ctx for ctx in model.contexts)
        assert get_context() is parent
    finally:
        reset_context(token)


def test_schema_error_is_repaired_before_tool_executes(monkeypatch):
    called = []

    async def submit(value):
        called.append(value)
        return "成功"

    invalid = AIMessage(content="", tool_calls=[{"id": "bad", "name": "submit_test", "args": {}}])
    _, model, _ = run(monkeypatch, [invalid, call("good")], submit)
    assert called == ["good"]
    assert len(model.seen) == 2


def test_persistent_tool_error_stops_after_two_corrections(monkeypatch):
    called = []

    async def submit(value):
        called.append(value)
        raise ValueError("匹配失败")

    with pytest.raises(ValueError, match="纠错次数已用尽"):
        run(monkeypatch, [call("bad", str(i)) for i in range(4)], submit)
    assert len(called) == 3


def test_missing_submission_is_repaired_in_same_context(monkeypatch):
    async def submit(value):
        return "成功"

    result, model, _ = run(
        monkeypatch,
        [AIMessage(content="正文已经写完"), call("完整正文")],
        submit,
    )

    assert len(model.seen) == 2
    assert model.seen[1][-2].content == "正文已经写完"
    assert "必须使用 submit_test 工具来结束任务" in model.seen[1][-1].content
    assert "任务未完成则继续" in model.seen[1][-1].content
    assert result["messages"][-1].status == "success"


def test_missing_submission_stops_after_two_corrections(monkeypatch):
    async def submit(value):
        pytest.fail("工具不应执行")

    with pytest.raises(RuntimeError, match="连续未调用 submit_test"):
        run(monkeypatch, [AIMessage(content="没有提交") for _ in range(3)], submit)


def test_model_failure_has_no_correction_loop(monkeypatch):
    async def submit(value):
        pytest.fail("工具不应执行")

    with pytest.raises(RuntimeError, match="模型不可用"):
        run(monkeypatch, [RuntimeError("模型不可用")], submit)


def test_programming_error_is_not_treated_as_correctable_parameters(monkeypatch):
    async def submit(value):
        raise RuntimeError("内部执行故障")

    with pytest.raises(RuntimeError, match="内部执行故障"):
        run(monkeypatch, [call("good")], submit)


def test_multiple_submissions_are_rejected_before_side_effects(monkeypatch):
    called = []

    async def submit(value):
        called.append(value)
        return "成功"

    batch = AIMessage(content="", tool_calls=call("first", "a").tool_calls + call("second", "b").tool_calls)
    _, model, _ = run(monkeypatch, [batch, call("fixed")], submit)
    assert called == ["fixed"]
    assert all(message.status == "error" for message in model.seen[1][-2:])


def test_isolated_subagent_inherits_session_for_model_headers(monkeypatch):
    async def submit(value):
        return '成功'
    token = set_context({'session_id': 'session-123', 'work_id': 'w'})
    try:
        _, model, _ = run(monkeypatch, [call('ok')], submit)
        assert model.contexts[0]['session_id'] == 'session-123'
    finally:
        reset_context(token)


def test_stream_reports_validation_and_correction_before_requesting_again(monkeypatch):
    from langchain_core.messages import AIMessageChunk
    class StreamModel(Model):
        async def astream(self, messages, config=None):
            self.seen.append(list(messages))
            value = {} if len(self.seen) == 1 else {'value': '完整结果'}
            yield AIMessageChunk(content='', tool_call_chunks=[{
                'name': 'submit_test', 'id': str(len(self.seen)), 'index': 0,
                'args': json.dumps(value, ensure_ascii=False)}])
    model = StreamModel([])
    monkeypatch.setattr('services.agents.llm.get_deep_agent_model', lambda **kw: model)
    async def submit(value):
        return value
    events = []
    async def emit(event, data):
        events.append((event, data))
    tool = StructuredTool.from_function(coroutine=submit, name='submit_test', description='提交', args_schema=Submission)
    asyncio.run(invoke_isolated_subagent(name='storyboard_designer', system_prompt='完整规则', task={}, tools=[tool], emit=emit))
    progress = [data for event, data in events if event == 'stage_progress']
    assert [data['stage'] for data in progress] == ['validating', 'correcting', 'validating']
    assert progress[1]['attempt'] == 1 and progress[1]['detail']
    starts = [data['label'] for event, data in events if event == 'stage_start']
    assert starts[1] == '正在修正提交（第 1 次）'
