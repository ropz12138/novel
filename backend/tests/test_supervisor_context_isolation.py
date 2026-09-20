"""Supervisor 请求级上下文并发隔离。"""
import asyncio

from services.agents import supervisor as supervisor_mod


def test_concurrent_tasks_keep_separate_contexts_in_async_and_worker_threads():
    both_bound = asyncio.Event()
    bound_count = 0
    bound_lock = asyncio.Lock()

    async def worker(user_id: str, work_id: str):
        nonlocal bound_count
        token = supervisor_mod.set_context({"user_id": user_id, "work_id": work_id})
        try:
            async with bound_lock:
                bound_count += 1
                if bound_count == 2:
                    both_bound.set()
            await both_bound.wait()
            await asyncio.sleep(0)
            async_context = dict(supervisor_mod.get_context())
            thread_context = await asyncio.to_thread(
                lambda: dict(supervisor_mod.get_context())
            )
            return async_context, thread_context
        finally:
            supervisor_mod.reset_context(token)

    async def run_both():
        return await asyncio.gather(
            worker("user-a", "work-a"),
            worker("user-b", "work-b"),
        )

    first, second = asyncio.run(run_both())
    assert first == (
        {"user_id": "user-a", "work_id": "work-a"},
        {"user_id": "user-a", "work_id": "work-a"},
    )
    assert second == (
        {"user_id": "user-b", "work_id": "work-b"},
        {"user_id": "user-b", "work_id": "work-b"},
    )


def test_reset_context_restores_previous_binding():
    outer = supervisor_mod.set_context({"work_id": "outer"})
    try:
        inner = supervisor_mod.set_context({"work_id": "inner"})
        assert supervisor_mod.get_context()["work_id"] == "inner"
        supervisor_mod.reset_context(inner)
        assert supervisor_mod.get_context()["work_id"] == "outer"
    finally:
        supervisor_mod.reset_context(outer)


def test_shared_agent_instance_keeps_emit_channels_separate(monkeypatch):
    both_running = asyncio.Event()
    running_count = 0
    running_lock = asyncio.Lock()

    class FakeGraph:
        def __init__(self, emit):
            self.emit = emit

        async def astream(self, *args, **kwargs):
            nonlocal running_count
            async with running_lock:
                running_count += 1
                if running_count == 2:
                    both_running.set()
            await both_running.wait()
            await self.emit("probe", {"work_id": supervisor_mod.get_context()["work_id"]})
            if False:
                yield None

    monkeypatch.setattr(
        supervisor_mod.SupervisorAgent,
        "_build_graph",
        lambda self, **kwargs: FakeGraph(kwargs["emit"]),
    )
    monkeypatch.setattr(
        supervisor_mod.SupervisorAgent,
        "_load_model_pref",
        lambda self, user_id: None,
    )
    monkeypatch.setattr(
        supervisor_mod.SupervisorAgent,
        "_load_chat_history",
        lambda self, session_id: ([], []),
    )

    first_events = []
    second_events = []

    async def first_emit(event, data):
        first_events.append((event, data))

    async def second_emit(event, data):
        second_events.append((event, data))

    agent = supervisor_mod.SupervisorAgent()

    async def run_both():
        await asyncio.gather(
            agent.run("first", {"work_id": "work-a"}, emit=first_emit),
            agent.run("second", {"work_id": "work-b"}, emit=second_emit),
        )

    asyncio.run(run_both())

    assert ("probe", {"work_id": "work-a"}) in first_events
    assert ("probe", {"work_id": "work-b"}) in second_events
    assert ("probe", {"work_id": "work-b"}) not in first_events
    assert ("probe", {"work_id": "work-a"}) not in second_events
