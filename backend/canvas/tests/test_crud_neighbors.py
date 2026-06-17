"""瘦 CRUD 工具测试 — TDD：返回增量 + 一级邻居。

create_node 去坐标参数、改用 layer；所有写入工具返回本次操作结果 + 一级邻居
（双向 incoming/outgoing，精简字段 id/type/title/layer，带 edge_type + direction）。
"""
import importlib
import json

from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node
from app.models.edge import Edge

nt = importlib.import_module("app.services.agents.tools.node_tools")


def _make_work(monkeypatch, db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def test_create_node_accepts_layer_no_position(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._create_node_sync("outline", "主线", content="x", layer=1))
        assert result["success"] is True
        assert result["node"]["layer"] == 1
        assert result["node"]["type"] == "outline"
        assert result["neighbors"] == []
    finally:
        db.close()


def test_update_node_returns_all_neighbors(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        a = Node(work_id=work.id, type="outline", title="A", layer=1)
        b = Node(work_id=work.id, type="chapter", title="B", layer=3)
        db.add_all([a, b])
        db.commit()
        db.add(Edge(work_id=work.id, source_id=a.id, target_id=b.id, edge_type="包含"))
        db.commit()

        result = json.loads(nt._update_node_sync(a.id, title="A改"))
        assert result["success"] is True
        assert result["node"]["title"] == "A改"

        neighbor_ids = [nb["node"]["id"] for nb in result["neighbors"]]
        assert b.id in neighbor_ids
        nb_b = next(nb for nb in result["neighbors"] if nb["node"]["id"] == b.id)
        assert set(nb_b["node"].keys()) == {"id", "type", "title", "layer"}
        assert nb_b["edge"]["direction"] == "out"
        assert nb_b["edge"]["edge_type"] == "包含"
    finally:
        db.close()


def test_delete_node_returns_orphaned_neighbors(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        a = Node(work_id=work.id, type="idea", title="A")
        b = Node(work_id=work.id, type="idea", title="B")
        c = Node(work_id=work.id, type="idea", title="C")
        db.add_all([a, b, c])
        db.commit()
        db.add(Edge(work_id=work.id, source_id=a.id, target_id=b.id, edge_type="x"))
        db.add(Edge(work_id=work.id, source_id=b.id, target_id=c.id, edge_type="y"))
        db.commit()

        result = json.loads(nt._delete_node_sync(b.id))
        assert result["success"] is True
        neighbor_ids = [nb["node"]["id"] for nb in result["neighbors"]]
        assert set(neighbor_ids) == {a.id, c.id}
        assert db.query(Node).filter_by(id=b.id).first() is None
    finally:
        db.close()


def test_create_edge_returns_endpoints_as_neighbors(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        a = Node(work_id=work.id, type="outline", title="A", layer=1)
        b = Node(work_id=work.id, type="chapter", title="B", layer=3)
        db.add_all([a, b])
        db.commit()

        result = json.loads(nt._create_edge_sync(a.id, b.id, edge_type="包含"))
        assert result["success"] is True
        neighbor_ids = [nb["node"]["id"] for nb in result["neighbors"]]
        assert set(neighbor_ids) == {a.id, b.id}
    finally:
        db.close()


def test_neighbor_incoming_direction(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        a = Node(work_id=work.id, type="outline", title="A", layer=1)
        b = Node(work_id=work.id, type="chapter", title="B", layer=3)
        db.add_all([a, b])
        db.commit()
        # a -> b：对 b 而言是 incoming
        db.add(Edge(work_id=work.id, source_id=a.id, target_id=b.id, edge_type="包含"))
        db.commit()

        result = json.loads(nt._update_node_sync(b.id, title="B改"))
        nb_a = next(nb for nb in result["neighbors"] if nb["node"]["id"] == a.id)
        assert nb_a["edge"]["direction"] == "in"
    finally:
        db.close()


def test_batch_create_nodes_returns_layer(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        result = json.loads(nt._batch_create_nodes_sync([
            {"node_type": "outline", "title": "A", "layer": 1},
            {"node_type": "chapter", "title": "B", "layer": 3},
        ]))
        assert result["success"] is True
        assert len(result["nodes"]) == 2
        assert all("layer" in n for n in result["nodes"])
        # 新建节点无边，无邻居
        assert result["neighbors"] == []
    finally:
        db.close()


def test_batch_create_edges_returns_endpoints(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        a = Node(work_id=work.id, type="outline", title="A", layer=1)
        b = Node(work_id=work.id, type="chapter", title="B", layer=3)
        db.add_all([a, b])
        db.commit()

        result = json.loads(nt._batch_create_edges_sync([
            {"source_id": a.id, "target_id": b.id, "edge_type": "包含"},
        ]))
        assert result["success"] is True
        neighbor_ids = [nb["id"] for nb in result["neighbors"]]
        assert set(neighbor_ids) == {a.id, b.id}
    finally:
        db.close()


def test_delete_edge_returns_affected_endpoints(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        a = Node(work_id=work.id, type="outline", title="A", layer=1)
        b = Node(work_id=work.id, type="chapter", title="B", layer=3)
        db.add_all([a, b])
        db.commit()
        e = Edge(work_id=work.id, source_id=a.id, target_id=b.id, edge_type="包含")
        db.add(e)
        db.commit()

        result = json.loads(nt._delete_edge_sync(e.id))
        assert result["success"] is True
        neighbor_ids = [nb["id"] for nb in result["neighbors"]]
        assert set(neighbor_ids) == {a.id, b.id}
    finally:
        db.close()
