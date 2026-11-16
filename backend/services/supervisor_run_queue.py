"""单进程 Supervisor 会话队列；任务状态由后端持有，与 SSE 订阅无关。"""
import asyncio
from collections import deque


class SupervisorRunQueue:
    def __init__(self):
        self.tasks = {}
        self._pending = {}
        self._wake = {}

    def running(self, session_id):
        task = self.tasks.get(session_id)
        return task is not None and not task.done()

    def pending(self, session_id):
        return list(self._pending.get(session_id, ()))

    def attach(self, session_id, wake):
        self._wake[session_id] = wake

    def take_pending(self, session_id):
        pending = self._pending.get(session_id)
        if pending is None:
            return []
        messages = list(pending)
        pending.clear()
        return messages

    def submit(self, session_id, item, execute):
        if self.running(session_id):
            self._pending[session_id].append(item)
            if session_id in self._wake:
                self._wake[session_id]()
            return
        self._pending[session_id] = deque([item])

        async def drain():
            try:
                while self._pending[session_id]:
                    current = self._pending[session_id].popleft()
                    await execute(current)
            finally:
                self._wake.pop(session_id, None)
                self._pending.pop(session_id, None)
                self.tasks.pop(session_id, None)

        self.tasks[session_id] = asyncio.create_task(drain())

    async def stop(self, session_id):
        if not self.running(session_id):
            return False
        self._pending[session_id].clear()
        task = self.tasks[session_id]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # A task cancelled before its first execution does not enter finally.
        self._wake.pop(session_id, None)
        self.tasks.pop(session_id, None)
        self._pending.pop(session_id, None)
        return True


supervisor_run_queue = SupervisorRunQueue()
