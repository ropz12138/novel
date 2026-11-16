import asyncio
import json

from langchain_core.messages import HumanMessage, ToolMessage
from services.agents.deep_agent_runtime import RuntimeInputMiddleware
from services.agents.run_control import AgentRunControl
from services.agents.supervisor import set_context, reset_context


def test_injects_users_and_child_results_before_next_model():
    async def run():
        pending = ['用户补充']
        async def take():
            result = [HumanMessage(content=text) for text in pending]
            pending.clear()
            return result
        control = AgentRunControl(take_user_messages=take, has_user_messages=lambda: bool(pending))
        async def execute(child):
            return {'success': True, 'content': '已保存'}
        child = control.start('writer', 'chapter', execute)
        await child.handle
        token = set_context({'run_control': control})
        try:
            middleware = RuntimeInputMiddleware()
            update = await middleware.abefore_model({'messages': []}, None)
            assert update['messages'][0].content == '用户补充'
            assert child.id in update['messages'][1].content
            assert await middleware.abefore_model({'messages': []}, None) is None
        finally:
            reset_context(token)
    asyncio.run(run())


def test_waiting_supervisor_wakes_on_new_user_message():
    async def run():
        pending = []
        async def take():
            result = [HumanMessage(content=text) for text in pending]
            pending.clear()
            return result
        control = AgentRunControl(take_user_messages=take, has_user_messages=lambda: bool(pending))
        async def blocked(child):
            await asyncio.Event().wait()
        control.start('writer', 'chapter', blocked)
        token = set_context({'run_control': control})
        try:
            middleware = RuntimeInputMiddleware()
            waiting = asyncio.create_task(middleware.aafter_agent({'messages': [ToolMessage(
                content=json.dumps({'success': True}), name='respond_to_user', tool_call_id='1')]}, None))
            await asyncio.sleep(0)
            assert not waiting.done()
            pending.append('新要求')
            control.wake()
            result = await asyncio.wait_for(waiting, 1)
            assert result['jump_to'] == 'model'
            assert result['messages'][0].content == '新要求'
        finally:
            await control.close()
            reset_context(token)
    asyncio.run(run())


def test_child_notices_restore_as_context_but_are_hidden_from_chat():
    from services.message_langchain import db_message_dicts_to_langchain
    from services.session_history_page import select_history_page
    event = {'id': 'e', 'role': 'agent_event', 'content': '子任务完成通知',
             'sort_order': 1, 'meta': {'type': 'subagent_result'}}
    restored = db_message_dicts_to_langchain([event])
    assert len(restored) == 1 and restored[0].content == '子任务完成通知'
    assert select_history_page([event], before_sort_order=None, limit=40)[0] == []


def test_wait_without_tasks_requests_another_model_step():
    from services.agents.tools.subagent_task_tools import wait_for_subagents
    from services.agents.deep_agent_runtime import RequireToolCallMiddleware
    async def run():
        token = set_context({'run_control': AgentRunControl()})
        try:
            result = await wait_for_subagents.ainvoke({})
            assert json.loads(result)['success'] is False
            update = await RequireToolCallMiddleware(completion_tool_name='respond_to_user').aafter_agent(
                {'messages': [ToolMessage(name='wait_for_subagents', content=result, tool_call_id='wait')]}, None)
            assert update['jump_to'] == 'model'
        finally:
            reset_context(token)
    asyncio.run(run())
