"""短剧流可重新订阅；连接关闭不取消已接受的生成。"""
import asyncio
from dataclasses import dataclass, field


@dataclass
class DramaStream:
    chapter_id: str = ''
    events: list = field(default_factory=list)
    done: bool = False
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def emit(self, event, data):
        async with self.changed:
            self.events.append((event, data))
            self.changed.notify_all()

    async def finish(self):
        async with self.changed:
            self.done = True
            self.changed.notify_all()

    async def subscribe(self, heartbeat_seconds):
        index = 0
        yield None
        while True:
            async with self.changed:
                try:
                    await asyncio.wait_for(self.changed.wait_for(lambda: index < len(self.events) or self.done), heartbeat_seconds)
                except asyncio.TimeoutError:
                    batch = [None]
                else:
                    batch = self.events[index:]
                    index = len(self.events)
                    if self.done and not batch:
                        return
            for item in batch:
                yield item


streams = {}
tasks = set()
