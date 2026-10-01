"""Supervisor 流事件的进程内合并、缓冲与断点订阅。"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator


TERMINAL_EVENTS = frozenset({"supervisor_done", "supervisor_interrupted", "error"})


@dataclass
class _StoredEvent:
    start_seq: int
    end_seq: int
    event: str
    data: dict


@dataclass
class _Subscriber:
    queue: asyncio.Queue
    last_sent_seq: int


@dataclass
class _RunStream:
    next_seq: int = 1
    sealed: list[_StoredEvent] = field(default_factory=list)
    pending: list[_StoredEvent] = field(default_factory=list)
    subscribers: list[_Subscriber] = field(default_factory=list)
    resume_after_seq: int = 0
    done: bool = False


class SupervisorStreamBroker:
    def __init__(self, *, max_pending_events: int = 32, max_pending_bytes: int = 4096):
        self._streams: dict[str, _RunStream] = {}
        self._max_pending_events = max_pending_events
        self._max_pending_bytes = max_pending_bytes

    def begin(self, session_id: str) -> None:
        self._streams[session_id] = _RunStream()

    def has_stream(self, session_id: str) -> bool:
        return session_id in self._streams

    @staticmethod
    def _merge_key(stored: _StoredEvent) -> tuple | None:
        data = stored.data
        if stored.event == "supervisor_stream":
            return stored.event, data.get("phase", "content")
        if stored.event == "node_content_diff_preview" and data.get("phase") == "delta":
            return stored.event, data.get("node_id"), "delta"
        return None

    @staticmethod
    def _event_bytes(stored: _StoredEvent) -> int:
        return len(str(stored.data.get("chunk") or "").encode("utf-8"))

    def _flush_pending(self, stream: _RunStream) -> None:
        if not stream.pending:
            return
        first = stream.pending[0]
        if self._merge_key(first) is None:
            stream.sealed.extend(stream.pending)
        else:
            data = dict(first.data)
            data["chunk"] = "".join(str(item.data.get("chunk") or "") for item in stream.pending)
            stream.sealed.append(_StoredEvent(
                start_seq=first.start_seq,
                end_seq=stream.pending[-1].end_seq,
                event=first.event,
                data=data,
            ))
        stream.pending.clear()

    async def publish(self, session_id: str, event: str, data: dict) -> None:
        stream = self._streams.get(session_id)
        if stream is None:
            raise RuntimeError(f"Supervisor stream not started: {session_id}")
        seq = stream.next_seq
        stream.next_seq += 1
        stored = _StoredEvent(seq, seq, event, dict(data or {}))

        pending_key = self._merge_key(stream.pending[0]) if stream.pending else None
        stored_key = self._merge_key(stored)
        if stream.pending and pending_key != stored_key:
            self._flush_pending(stream)
        stream.pending.append(stored)

        pending_bytes = sum(self._event_bytes(item) for item in stream.pending)
        if (
            stored_key is None
            or len(stream.pending) >= self._max_pending_events
            or pending_bytes >= self._max_pending_bytes
        ):
            self._flush_pending(stream)

        for subscriber in tuple(stream.subscribers):
            subscriber.queue.put_nowait((seq, event, dict(data or {})))

        if event in TERMINAL_EVENTS:
            self._flush_pending(stream)
            stream.done = True
            for subscriber in tuple(stream.subscribers):
                subscriber.queue.put_nowait(None)
            asyncio.get_running_loop().call_later(300, self._expire, session_id, stream)

    def _expire(self, session_id: str, expected: _RunStream) -> None:
        if self._streams.get(session_id) is expected and expected.done:
            self._streams.pop(session_id, None)

    def stats(self, session_id: str) -> dict[str, int]:
        stream = self._streams[session_id]
        return {
            "sealed_batches": len(stream.sealed),
            "pending_events": len(stream.pending),
        }

    async def subscribe(self, session_id: str) -> AsyncIterator[tuple[str, dict]]:
        stream = self._streams.get(session_id)
        if stream is None:
            return
        queue: asyncio.Queue = asyncio.Queue()
        subscriber = _Subscriber(queue=queue, last_sent_seq=stream.resume_after_seq)

        for stored in stream.sealed:
            if stored.end_seq > stream.resume_after_seq:
                queue.put_nowait((stored.end_seq, stored.event, dict(stored.data)))
        pending = [item for item in stream.pending if item.end_seq > stream.resume_after_seq]
        if pending:
            first = pending[0]
            data = dict(first.data)
            if self._merge_key(first) is not None:
                data["chunk"] = "".join(str(item.data.get("chunk") or "") for item in pending)
            queue.put_nowait((pending[-1].end_seq, first.event, data))
        if stream.done:
            queue.put_nowait(None)
        else:
            stream.subscribers.append(subscriber)

        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                seq, event, data = item
                subscriber.last_sent_seq = seq
                stream.resume_after_seq = max(stream.resume_after_seq, seq)
                yield event, data
        finally:
            if subscriber in stream.subscribers:
                stream.subscribers.remove(subscriber)
            stream.resume_after_seq = max(stream.resume_after_seq, subscriber.last_sent_seq)


supervisor_stream_broker = SupervisorStreamBroker()
