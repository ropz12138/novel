import asyncio

import pytest

from services.supervisor_stream_broker import SupervisorStreamBroker


@pytest.mark.parametrize("event,data", [
    ("supervisor_stream", {"phase": "content"}),
    ("supervisor_stream", {"phase": "reasoning"}),
    ("node_content_diff_preview", {"phase": "delta", "node_id": "chapter-1"}),
])
@pytest.mark.parametrize("after_seq,expected", [(0, "甲🙂乙丙"), (1, "乙丙"), (2, "丙"), (3, "")])
def test_reconnect_inside_sealed_batch_replays_only_unseen_chunks(event, data, after_seq, expected):
    async def run():
        broker = SupervisorStreamBroker(max_pending_events=3)
        broker.begin("session-1")
        for chunk in ("甲🙂", "乙", "丙"):
            await broker.publish("session-1", event, {**data, "chunk": chunk})
        await broker.publish("session-1", "supervisor_done", {})
        replay = [item async for item in broker.subscribe("session-1", after_seq=after_seq)]
        assert "".join(payload.get("chunk", "") for _, payload in replay) == expected
        assert replay[-1][0] == "supervisor_done"
        if expected:
            assert replay[0] == (event, {**data, "chunk": expected, "_stream_seq": 3})
    asyncio.run(run())


def test_reconnect_inside_batch_flushed_by_event_change():
    async def run():
        broker = SupervisorStreamBroker()
        broker.begin("session-1")
        for chunk in ("甲", "乙"):
            await broker.publish("session-1", "supervisor_stream", {"chunk": chunk})
        await broker.publish("session-1", "stage_start", {"stage": "tool"})
        await broker.publish("session-1", "supervisor_done", {})
        replay = [item async for item in broker.subscribe("session-1", after_seq=1)]
        assert replay == [
            ("supervisor_stream", {"chunk": "乙", "_stream_seq": 2}),
            ("stage_start", {"stage": "tool", "_stream_seq": 3}),
            ("supervisor_done", {"_stream_seq": 4}),
        ]
    asyncio.run(run())


def test_reconnect_replays_events_created_after_previous_stream_disconnected():
    async def run():
        broker = SupervisorStreamBroker(max_pending_events=8, max_pending_bytes=4096)
        broker.begin("session-1")
        first = broker.subscribe("session-1")
        await broker.publish("session-1", "supervisor_stream", {"chunk": "甲", "phase": "content"})
        assert (await first.__anext__())[1]["chunk"] == "甲"
        await first.aclose()

        await broker.publish("session-1", "supervisor_stream", {"chunk": "乙", "phase": "content"})
        await broker.publish("session-1", "supervisor_stream", {"chunk": "丙", "phase": "content"})

        resumed = broker.subscribe("session-1", after_seq=1)
        assert await resumed.__anext__() == (
            "supervisor_stream",
            {"chunk": "乙丙", "phase": "content", "_stream_seq": 3},
        )
        await resumed.aclose()

    asyncio.run(run())


def test_reconnect_cursor_is_owned_by_client_not_an_overlapping_old_subscriber():
    async def run():
        broker = SupervisorStreamBroker(max_pending_events=8, max_pending_bytes=4096)
        broker.begin("session-1")
        old = broker.subscribe("session-1", after_seq=0)
        await broker.publish("session-1", "chapter_edit_diff", {"node_id": "chapter-1"})

        event, data = await old.__anext__()
        assert event == "chapter_edit_diff"
        assert data["_stream_seq"] == 1

        # 服务端把事件交给旧连接，并不代表浏览器已经收到。新连接仍以客户端
        # 最后确认的序号 0 恢复，因此必须重新收到该事件。
        resumed = broker.subscribe("session-1", after_seq=0)
        assert await resumed.__anext__() == (
            "chapter_edit_diff",
            {"node_id": "chapter-1", "_stream_seq": 1},
        )
        await resumed.aclose()
        await old.aclose()

    asyncio.run(run())


def test_small_stream_events_are_coalesced_in_memory():
    async def run():
        broker = SupervisorStreamBroker(max_pending_events=3, max_pending_bytes=4096)
        broker.begin("session-1")
        for chunk in ("甲", "乙", "丙", "丁"):
            await broker.publish("session-1", "supervisor_stream", {
                "chunk": chunk,
                "phase": "content",
            })

        assert broker.stats("session-1") == {"sealed_batches": 1, "pending_events": 1}

    asyncio.run(run())


def test_unsealed_events_are_replayed_before_live_events():
    async def run():
        broker = SupervisorStreamBroker(max_pending_events=8, max_pending_bytes=4096)
        broker.begin("session-1")
        await broker.publish("session-1", "supervisor_stream", {
            "chunk": "尚未合并",
            "phase": "content",
        })

        subscription = broker.subscribe("session-1")
        assert (await subscription.__anext__())[1]["chunk"] == "尚未合并"
        await broker.publish("session-1", "stage_start", {"stage": "tool"})
        assert (await subscription.__anext__())[0] == "stage_start"
        await subscription.aclose()

    asyncio.run(run())
