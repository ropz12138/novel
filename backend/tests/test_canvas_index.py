"""get_canvas_index 工具测试 — TDD。

返回画布全量精简目录（不含正文），供 agent 做索引定位。
与 get_canvas_overview（统计聚合）区分。
"""
import importlib
import json

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node
from models.edge import Edge

qt = importlib.import_module("services.agents.tools.query_tools")


def _make_work(db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    return work


def _patch_work(monkeypatch, work_id):
    monkeypatch.setattr(qt, "_get_current_work_id", lambda: work_id)


def test_canvas_index_empty(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        _patch_work(monkeypatch, work.id)
        result = json.loads(qt._get_canvas_index_sync())
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["total_nodes"] == 0
        assert result["total_edges"] == 0
    finally:
        db.close()


def test_canvas_index_returns_compact_directory(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        _patch_work(monkeypatch, work.id)
        n1 = Node(work_id=work.id, type="outline", title="主线",
                  content="很长的正文不应该出现在索引里", layer=1)
        n2 = Node(work_id=work.id, type="chapter", title="第1章", layer=3)
        db.add_all([n1, n2])
        db.commit()
        db.add(Edge(work_id=work.id, source_id=n1.id, target_id=n2.id,
                    edge_type="包含", label=""))
        db.commit()

        result = json.loads(qt._get_canvas_index_sync())

        nodes = result["nodes"]
        assert len(nodes) == 2
        n1_item = next(n for n in nodes if n["id"] == n1.id)
        assert set(n1_item.keys()) == {"id", "type", "title", "layer"}
        assert n1_item["layer"] == 1
        assert "content" not in n1_item

        edges = result["edges"]
        assert len(edges) == 1
        assert edges[0]["edge_type"] == "包含"
        assert edges[0]["source_id"] == n1.id
        assert edges[0]["target_id"] == n2.id
    finally:
        db.close()


def test_canvas_index_scoped_to_current_work(monkeypatch):
    db = database.SessionLocal()
    try:
        work1 = _make_work(db)
        work2 = CanvasWork(user_id=work1.user_id, title="w2")
        db.add(work2)
        db.commit()
        db.add(Node(work_id=work1.id, type="idea", title="w1节点"))
        db.add(Node(work_id=work2.id, type="idea", title="w2节点"))
        db.commit()

        _patch_work(monkeypatch, work1.id)
        result = json.loads(qt._get_canvas_index_sync())
        titles = [n["title"] for n in result["nodes"]]
        assert titles == ["w1节点"]
    finally:
        db.close()


def test_get_canvas_index_tool_registered():
    names = [t.name for t in qt.query_tools]
    assert "get_canvas_index" in names
