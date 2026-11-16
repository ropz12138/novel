import asyncio
import pytest

from services.agents.run_control import AgentRunControl


def test_parallel_children_steering_and_completion_order():
    async def scenario():
        control = AgentRunControl()
        gate = asyncio.Event()
        started = []
        async def execute(child):
            started.append(child.chapter_node_id)
            await gate.wait()
            return {'success': True, 'received': child.take_instructions()}
        first = control.start('writer', 'chapter-1', execute)
        second = control.start('writer', 'chapter-2', execute)
        await asyncio.sleep(0)
        assert started == ['chapter-1', 'chapter-2']
        control.steer(first.id, '保留钥匙')
        control.steer(first.id, '结尾到达仓库')
        third = control.start('reviewer', 'chapter-1', execute)
        assert third.id not in (first.id, second.id)
        gate.set()
        await asyncio.gather(first.handle, second.handle, third.handle)
        results = control.take_completions()
        first_result = next(item for item in results if item['task_id'] == first.id)
        assert first_result['result']['received'] == ['保留钥匙', '结尾到达仓库']
        assert not control.active()
        with pytest.raises(ValueError, match='结束'):
            control.steer(first.id, '迟到的要求')
    asyncio.run(scenario())


def test_wakeup_and_cleanup_preserve_written_results():
    async def scenario():
        control = AgentRunControl()
        gate = asyncio.Event()
        async def execute(child):
            await gate.wait()
            return {'success': True}
        child = control.start('writer', 'chapter-1', execute)
        waiting = asyncio.create_task(control.wait())
        await asyncio.sleep(0)
        control.wake()
        await asyncio.wait_for(waiting, 1)
        await control.close()
        assert child.handle.cancelled()
        assert not control.active()
    asyncio.run(scenario())


def test_review_tasks_can_run_for_the_same_chapter_in_separate_sessions():
    async def scenario():
        first, second = AgentRunControl(), AgentRunControl()
        async def blocked(child):
            await asyncio.Event().wait()
        first.start('reviewer', 'shared-chapter', blocked)
        second.start('reference_agent', 'shared-chapter', blocked)
        await first.close()
        await second.close()
        assert not first.active() and not second.active()
    asyncio.run(scenario())
