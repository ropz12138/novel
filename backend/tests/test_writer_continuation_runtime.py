import asyncio
import json
import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from services.agents.run_control import ChildTask
from services.agents.subagent_runtime import invoke_isolated_subagent


class Text(BaseModel):
    content: str


class Finish(BaseModel):
    pass


def test_write_then_steer_then_write_then_finish(monkeypatch):
    async def scenario():
        child = ChildTask(id='t', agent='writer', chapter_node_id='c')
        seen, writes = [], []
        responses = [
            AIMessage(content='', tool_calls=[{'name': 'write_content', 'args': {'content': '第一版'}, 'id': '1'}]),
            AIMessage(content='', tool_calls=[{'name': 'write_content', 'args': {'content': '第二版'}, 'id': '2'}]),
            AIMessage(content='', tool_calls=[{'name': 'finish_writing', 'args': {}, 'id': '3'}]),
        ]
        class Model:
            def bind_tools(self, tools):
                return self
            async def ainvoke(self, messages, **kwargs):
                seen.append(list(messages))
                if len(seen) == 1:
                    child.instructions.append('增加追逐情节')
                return responses.pop(0)
        monkeypatch.setattr('services.agents.llm.get_deep_agent_model', lambda **kwargs: Model())
        async def write(content):
            writes.append(content)
            return json.dumps({'success': True})
        async def finish():
            return json.dumps({'success': True})
        await invoke_isolated_subagent(name='writer', system_prompt='完整规则', task={'target': '原文'}, tools=[
            StructuredTool.from_function(coroutine=write, name='write_content', description='写入', args_schema=Text),
            StructuredTool.from_function(coroutine=finish, name='finish_writing', description='完成', args_schema=Finish),
        ], completion_tool_name='finish_writing', child_task=child)
        assert writes == ['第一版', '第二版']
        assert any('增加追逐情节' in str(message.content) for message in seen[1])
    asyncio.run(scenario())


def test_pending_instruction_prevents_finish_in_same_response(monkeypatch):
    async def scenario():
        child = ChildTask(id='t', agent='writer', chapter_node_id='c')
        finished = []
        class Model:
            calls = 0
            def bind_tools(self, tools):
                return self
            async def ainvoke(self, messages, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    child.instructions.append('修改结尾')
                return AIMessage(content='', tool_calls=[{'name': 'finish_writing', 'args': {}, 'id': str(self.calls)}])
        monkeypatch.setattr('services.agents.llm.get_deep_agent_model', lambda **kwargs: Model())
        async def finish():
            finished.append(True)
            return '{"success": true}'
        await invoke_isolated_subagent(name='writer', system_prompt='规则', task={}, tools=[
            StructuredTool.from_function(coroutine=finish, name='finish_writing', description='完成', args_schema=Finish),
        ], completion_tool_name='finish_writing', child_task=child)
        assert finished == [True]
    asyncio.run(scenario())


def test_writer_inherits_session_and_stops_immediately_on_source_conflict(monkeypatch):
    from services.agents.subagent_runtime import SourceChangedError
    from services.agents.supervisor import get_context, set_context, reset_context
    async def scenario():
        seen = []
        class Model:
            def bind_tools(self, tools):
                return self
            async def ainvoke(self, messages, **kwargs):
                seen.append(get_context().get('session_id'))
                return AIMessage(content='', tool_calls=[{'name': 'write_content', 'args': {'content': '新正文'}, 'id': '1'}])
        monkeypatch.setattr('services.agents.llm.get_deep_agent_model', lambda **kwargs: Model())
        async def write(content):
            raise SourceChangedError('来源已变化')
        token = set_context({'session_id': 'session-123'})
        try:
            with pytest.raises(SourceChangedError, match='来源已变化'):
                await invoke_isolated_subagent(name='writer', system_prompt='规则', task={}, tools=[
                    StructuredTool.from_function(coroutine=write, name='write_content', description='写入', args_schema=Text),
                ], completion_tool_name='finish_writing')
            assert seen == ['session-123']
        finally:
            reset_context(token)
    asyncio.run(scenario())


def test_finish_marks_child_finishing_before_emitting_progress(monkeypatch):
    from langchain_core.messages import AIMessageChunk
    async def scenario():
        child = ChildTask(id='streamed-child', agent='writer', chapter_node_id='c')
        class Model:
            def bind_tools(self, tools): return self
            async def astream(self, messages, **kwargs):
                yield AIMessageChunk(content='', tool_call_chunks=[dict(name='finish_writing', id='finish', index=0, args='{}')])
        monkeypatch.setattr('services.agents.llm.get_deep_agent_model', lambda **kwargs: Model())
        async def finish(): return '{"success": true}'
        async def emit(event, data):
            if event == 'tool_end':
                assert child.status == 'finishing'
        await invoke_isolated_subagent(name='writer', system_prompt='规则', task={}, tools=[
            StructuredTool.from_function(coroutine=finish, name='finish_writing', description='完成', args_schema=Finish),
        ], completion_tool_name='finish_writing', child_task=child, emit=emit)
    asyncio.run(scenario())
