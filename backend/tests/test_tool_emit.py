"""工具 emit 事件 TDD 测试。

覆盖以下行为：
- BUG #0（致命根因）：SupervisorAgent.run() 未把 emit 注入 context，
  导致所有工具的 _get_emit() 永远返回 None，emit 全部静默失效。
- BUG #A：_update_edge_async 成功时未触发 nodes_updated（且存在死代码）。
- 回归：_create_node_async 在 emit 注入后能正常触发 nodes_updated。
"""
import asyncio
import importlib
import json

from langchain_core.messages import AIMessage

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node
from models.edge import Edge

nt = importlib.import_module("services.agents.tools.node_tools")
supervisor_mod = importlib.import_module("services.agents.supervisor")
sat = importlib.import_module("services.agents.tools.specialist_agent_tools")
wat = importlib.import_module("services.agents.tools.workflow_agent_tools")
tt = importlib.import_module("services.agents.tools.todo_tools")


# ── 公共 fixtures ──

def _make_work(db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    return work


def _inject_emit(work_id, collector):
    """模拟修复后 run() 把 emit 注入 context 的状态。"""
    supervisor_mod.set_context({"work_id": work_id, "emit": collector})


def _clear_context():
    supervisor_mod.set_context({})


class _FakeGraph:
    """最小 graph 替身：不产任何事件，ainvoke 返回单条 AIMessage。"""

    async def astream_events(self, *a, **kw):
        if False:  # pragma: no cover - 仅为使其成为 async generator
            yield
        return

    async def ainvoke(self, *a, **kw):
        return {"messages": [AIMessage(content="ok")]}


def _make_collector():
    events = []

    async def collect(event, data):
        events.append((event, data))

    return collect, events


# ── BUG #0: run() 必须把 emit 注入 context ──

def test_run_injects_emit_into_context(monkeypatch):
    """run() 调用后，全局 context 应含 emit，使工具的 _get_emit() 能读到。"""
    monkeypatch.setattr(
        supervisor_mod.SupervisorAgent,
        "_build_graph",
        lambda self, **kwargs: _FakeGraph(),
    )

    collect, _ = _make_collector()
    agent = supervisor_mod.SupervisorAgent()
    try:
        asyncio.run(agent.run("hi", {"work_id": "w1"}, emit=collect))
    except Exception:
        # run 可能因 traceable/事件不完整抛错；本测试只关心 context 注入
        pass

    ctx = supervisor_mod.get_context()
    assert ctx.get("emit") is collect, "run() 未把 emit 注入 context（BUG #0）"


# ── BUG #A: _update_edge_async 触发 emit ──

def test_update_edge_async_emits_nodes_updated(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
        a = Node(sort_order=0, work_id=work.id, type="outline", title="A", layer=0)
        b = Node(sort_order=0, work_id=work.id, type="outline", title="B", layer=0)
        db.add_all([a, b])
        db.commit()
        e = Edge(work_id=work.id, source_id=a.id, target_id=b.id, edge_type="x")
        db.add(e)
        db.commit()

        collect, events = _make_collector()
        _inject_emit(work.id, collect)

        result = json.loads(asyncio.run(nt._update_edge_async(e.id, edge_type="y")))
        assert result["success"] is True
        assert any(ev == "nodes_updated" for ev, _ in events), \
            "_update_edge_async 未触发 nodes_updated（BUG #A）"
    finally:
        db.close()
        _clear_context()

# ── 回归：_create_node_async 在 emit 注入后能触发 emit ──

def test_create_node_async_emits_nodes_updated(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)

        collect, events = _make_collector()
        _inject_emit(work.id, collect)

        result = json.loads(asyncio.run(
            nt._create_node_async("outline", "回归节点", layer=0, position_x=0, position_y=0, sort_order=1)
        ))
        assert result["success"] is True
        assert any(ev == "nodes_updated" for ev, _ in events)
    finally:
        db.close()
        _clear_context()


def test_commit_chapter_emits_single_nodes_updated_event(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        chapter = Node(work_id=work.id, type="chapter", title="第一章", content="", sort_order=1)
        db.add(chapter)
        db.commit()
        work_id, chapter_id = work.id, chapter.id
    finally:
        db.close()
    draft = sat._create_artifact(work_id, chapter_id, "chapter_draft", "最终正文")
    collect, events = _make_collector()
    _inject_emit(work_id, collect)
    try:
        result = json.loads(asyncio.run(sat.commit_chapter_workflow_result.ainvoke({
            "chapter_node_id": chapter_id,
            "draft_artifact_id": draft.id,
            "expected_content_sha256": sat._content_sha256(""),
        })))
        assert result["gate"]["code"] == "chapter_committed"
        updates = [(event, data) for event, data in events if event == "nodes_updated"]
        assert updates == [("nodes_updated", {
            "action": "chapter_commit",
            "chapter_node_id": chapter_id,
            "content_changed": True,
        })]
        diffs = [(event, data) for event, data in events if event == "chapter_edit_diff"]
        assert len(diffs) == 1
        assert diffs[0][1]["chapter_node_id"] == chapter_id
        assert diffs[0][1]["original_content"] == ""
        assert diffs[0][1]["current_content"] == "最终正文"
        assert diffs[0][1]["diff"]["hunks"]
    finally:
        _clear_context()


def test_develop_existing_node_emits_single_nodes_updated_event(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        work_id = work.id
    finally:
        db.close()
    from models.node import Node
    db = database.SessionLocal()
    try:
        node = Node(work_id=work_id, type="outline", title="总纲", content="", sort_order=1)
        db.add(node)
        db.commit()
        node_id = node.id
    finally:
        db.close()

    async def fake_agent(*args, **kwargs):
        return {"nodes": [{"node_id": node_id, "content": "完整总纲"}]}

    monkeypatch.setattr(wat.sat, "_invoke_json_agent", fake_agent)
    collect, events = _make_collector()
    _inject_emit(work_id, collect)
    try:
        result = json.loads(asyncio.run(wat.develop_existing_nodes.ainvoke({
            "specialty": "outline", "node_ids": [node_id], "user_instruction": "完善总纲",
        })))
        assert result["gate"]["code"] == "nodes_written"
        updates = [(event, data) for event, data in events if event == "nodes_updated"]
        assert updates == [("nodes_updated", {
            "action": "direct_node_write",
            "node_ids": [node_id],
        })]
    finally:
        _clear_context()


def test_needs_user_gate_blocks_todo_completion(monkeypatch):
    called = False

    def unexpected_update(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(tt, "_update_todolist_sync", unexpected_update)
    supervisor_mod.set_context({
        "workflow_gate": {
            "passed": False,
            "code": "chapter_version_conflict",
            "status": "needs_user",
        },
    })
    try:
        result = asyncio.run(tt._update_todolist_async("complete", task_id="T5"))
        assert called is False
        assert result.startswith("失败：")
        assert "chapter_version_conflict" in result
    finally:
        _clear_context()
