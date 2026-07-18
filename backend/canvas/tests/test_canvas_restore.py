"""Canvas restore API 测试 — TDD

POST /api/works/{work_id}/canvas/restore
接收 CanvasSnapshot，将画布恢复到 snapshot 状态：
- snapshot 中的节点/边：upsert（更新或创建）
- 不在 snapshot 中的节点/边：删除
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import database
from app.routers.auth import get_current_user
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node
from app.models.edge import Edge

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth():
    """Mock 认证，每个测试创建独立用户"""
    db = database.SessionLocal()
    try:
        user = User(username="tester", email="t@t.t", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def _make_work(db, user_id):
    work = CanvasWork(user_id=user_id, title="test")
    db.add(work)
    db.commit()
    db.refresh(work)
    return work


def _make_node(db, work_id, title="n", layer=0, x=0.0, y=0.0):
    node = Node(work_id=work_id, type="outline", title=title, layer=layer,
                position_x=x, position_y=y)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def _make_edge(db, work_id, source_id, target_id, label=""):
    edge = Edge(work_id=work_id, source_id=source_id, target_id=target_id,
                edge_type="uses", label=label)
    db.add(edge)
    db.commit()
    db.refresh(edge)
    return edge


def _node_payload(node, **overrides):
    return {
        "id": node.id,
        "type": "outline",
        "title": node.title,
        "position_x": overrides.get("position_x", node.position_x),
        "position_y": overrides.get("position_y", node.position_y),
        "layer": overrides.get("layer", node.layer),
    }


# --- restore 恢复节点位置（undo 拖拽）---
def test_restore_updates_node_positions(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        node = _make_node(db, work.id, title="N1", x=100, y=200)

        resp = client.post(f"/api/works/{work.id}/canvas/restore", json={
            "nodes": [_node_payload(node, position_x=50, position_y=60)],
            "edges": [],
        })

        assert resp.status_code == 200
        db.expire_all()
        refreshed = db.query(Node).filter(Node.id == node.id).first()
        assert refreshed.position_x == 50
        assert refreshed.position_y == 60
    finally:
        db.close()


# --- restore 删除 snapshot 中没有的节点（undo 创建节点）---
def test_restore_deletes_extra_nodes(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        keep = _make_node(db, work.id, title="keep")
        gone = _make_node(db, work.id, title="gone")
        keep_id, gone_id = keep.id, gone.id

        resp = client.post(f"/api/works/{work.id}/canvas/restore", json={
            "nodes": [_node_payload(keep)],
            "edges": [],
        })

        assert resp.status_code == 200
        db.expire_all()
        assert db.query(Node).filter(Node.id == gone_id).first() is None
        assert db.query(Node).filter(Node.id == keep_id).first() is not None
    finally:
        db.close()


# --- restore 创建 snapshot 中有但 DB 没有的节点（undo 删除节点）---
def test_restore_creates_missing_nodes(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        new_id = str(uuid.uuid4())

        resp = client.post(f"/api/works/{work.id}/canvas/restore", json={
            "nodes": [{
                "id": new_id, "type": "outline", "title": "restored",
                "position_x": 10, "position_y": 20, "layer": 1,
                "content": "hello",
            }],
            "edges": [],
        })

        assert resp.status_code == 200
        db.expire_all()
        created = db.query(Node).filter(Node.id == new_id).first()
        assert created is not None
        assert created.title == "restored"
        assert created.position_x == 10
        assert created.layer == 1
    finally:
        db.close()


# --- restore 删除 snapshot 中没有的边 ---
def test_restore_deletes_extra_edges(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        a = _make_node(db, work.id, title="A")
        b = _make_node(db, work.id, title="B")
        c = _make_node(db, work.id, title="C")
        keep_edge = _make_edge(db, work.id, a.id, b.id, label="keep")
        gone_edge = _make_edge(db, work.id, b.id, c.id, label="gone")
        keep_edge_id, gone_edge_id = keep_edge.id, gone_edge.id

        resp = client.post(f"/api/works/{work.id}/canvas/restore", json={
            "nodes": [_node_payload(a), _node_payload(b), _node_payload(c)],
            "edges": [{
                "id": keep_edge_id, "source_id": a.id, "target_id": b.id,
                "edge_type": "uses", "label": "keep",
            }],
        })

        assert resp.status_code == 200
        db.expire_all()
        assert db.query(Edge).filter(Edge.id == gone_edge_id).first() is None
        assert db.query(Edge).filter(Edge.id == keep_edge_id).first() is not None
    finally:
        db.close()


# --- restore 返回正确计数 ---
def test_restore_returns_correct_counts(mock_auth):
    db = database.SessionLocal()
    try:
        work = _make_work(db, mock_auth.id)
        a = _make_node(db, work.id, title="A")
        b = _make_node(db, work.id, title="B")

        resp = client.post(f"/api/works/{work.id}/canvas/restore", json={
            "nodes": [_node_payload(a), _node_payload(b)],
            "edges": [{
                "id": str(uuid.uuid4()), "source_id": a.id, "target_id": b.id,
                "edge_type": "uses", "label": "link",
            }],
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["node_count"] == 2
        assert data["edge_count"] == 1
    finally:
        db.close()


# --- restore 不存在的 work → 404 ---
def test_restore_nonexistent_work_returns_404(mock_auth):
    resp = client.post("/api/works/nonexistent-id/canvas/restore", json={
        "nodes": [], "edges": [],
    })
    assert resp.status_code == 404
