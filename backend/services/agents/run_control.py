"""一次 Supervisor 执行中的子任务、补充指令与唤醒信号。"""
from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field


@dataclass
class ChildTask:
    id: str
    agent: str
    chapter_node_id: str | None
    instructions: deque = field(default_factory=deque)
    handle: asyncio.Task | None = None
    status: str = 'running'
    result: dict | None = None

    def take_instructions(self):
        messages = list(self.instructions)
        self.instructions.clear()
        return messages


class AgentRunControl:
    def __init__(self, *, take_user_messages=None, has_user_messages=None):
        self.children = {}
        self.mutation_lock = asyncio.Lock()
        self._completions = deque()
        self._changed = asyncio.Event()
        self.take_user_messages = take_user_messages
        self.has_user_messages = has_user_messages or (lambda: False)

    def active(self):
        return [child for child in self.children.values() if child.status == 'running']

    def wake(self):
        self._changed.set()

    def start(self, agent, chapter_node_id, execute):
        child = ChildTask(id=uuid.uuid4().hex, agent=agent, chapter_node_id=chapter_node_id)
        self.children[child.id] = child

        async def run():
            try:
                result = await execute(child)
            except asyncio.CancelledError:
                child.status = 'cancelled'
                raise
            except Exception as exc:
                result = {'success': False, 'error': str(exc)}
            child.result = result
            child.status = 'completed' if result.get('success') else 'failed'
            self._completions.append({'task_id': child.id, 'agent': agent,
                                      'chapter_node_id': chapter_node_id, 'result': result})
            self.wake()
            return result

        child.handle = asyncio.create_task(run(), name=f'{agent}:{child.id}')
        return child

    def steer(self, task_id, message):
        child = self.children.get(task_id)
        if child is None:
            raise ValueError('子任务不存在于当前执行中')
        if child.status != 'running':
            raise ValueError('子任务已经结束，请根据结果派发新的任务')
        child.instructions.append(message)

    def ready(self):
        return bool(self._completions) or self.has_user_messages()

    def take_completions(self):
        results = list(self._completions)
        self._completions.clear()
        return results

    async def wait(self):
        self._changed.clear()
        if self._completions or self.has_user_messages():
            return
        await self._changed.wait()

    async def close(self):
        handles = [child.handle for child in self.active()]
        for handle in handles:
            handle.cancel()
        if handles:
            await asyncio.gather(*handles, return_exceptions=True)
        for child in self.children.values():
            if child.handle.cancelled():
                child.status = 'cancelled'


def current_run_control():
    from services.agents.supervisor import get_context
    context = get_context()
    if 'run_control' not in context:
        context['run_control'] = AgentRunControl()
    return context['run_control']
