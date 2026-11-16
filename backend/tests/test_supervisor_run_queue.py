import asyncio

from services.supervisor_run_queue import SupervisorRunQueue


def test_serializes_messages_without_cancelling_active_run():
    async def run():
        queue = SupervisorRunQueue()
        gate = asyncio.Event()
        started = []

        async def execute(item):
            started.append(item["content"])
            if item["content"] == "改":
                await gate.wait()

        queue.submit("s", {"content": "改"}, execute)
        await asyncio.sleep(0)
        queue.submit("s", {"content": "继续"}, execute)
        queue.submit("s", {"content": "检查"}, execute)
        assert started == ["改"]
        assert [item["content"] for item in queue.pending("s")] == ["继续", "检查"]
        gate.set()
        await queue.tasks["s"]
        assert started == ["改", "继续", "检查"]
        assert not queue.running("s")
    asyncio.run(run())


def test_stop_cancels_active_run_and_discards_waiting_messages():
    async def run():
        queue = SupervisorRunQueue()
        started = []

        async def execute(item):
            started.append(item["content"])
            await asyncio.Event().wait()

        queue.submit("s", {"content": "改"}, execute)
        await asyncio.sleep(0)
        queue.submit("s", {"content": "继续"}, execute)
        assert await queue.stop("s")
        assert started == ["改"]
        assert queue.pending("s") == []
        assert not queue.running("s")
    asyncio.run(run())


def test_claimed_messages_enter_active_run_once_and_wake_it():
    async def run():
        queue = SupervisorRunQueue()
        gate = asyncio.Event()
        started, injected, wakes = [], [], []
        async def execute(item):
            started.append(item['content'])
            queue.attach('s', lambda: wakes.append(True))
            await gate.wait()
            injected.extend(queue.take_pending('s'))
        queue.submit('s', {'content': '原任务'}, execute)
        await asyncio.sleep(0)
        queue.submit('s', {'content': '补充一'}, execute)
        queue.submit('s', {'content': '补充二'}, execute)
        assert len(wakes) == 2
        gate.set()
        await queue.tasks['s']
        assert started == ['原任务']
        assert [item['content'] for item in injected] == ['补充一', '补充二']
        assert queue.take_pending('s') == []
    asyncio.run(run())
