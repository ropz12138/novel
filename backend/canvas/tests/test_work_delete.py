"""删除作品 API — TDD。"""
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
    db = database.SessionLocal()
    try:
        owner = User(username="owner", email="owner@t.t", password_hash="x")
        other = User(username="other", email="other@t.t", password_hash="x")
        db.add_all([owner, other])
        db.commit()
        db.refresh(owner)
        db.refresh(other)
        app.dependency_overrides[get_current_user] = lambda: owner
        yield {"owner": owner, "other": other}
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def _make_work(db, user_id, title="测试作品"):
    work = CanvasWork(user_id=user_id, title=title)
    db.add(work)
    db.commit()
    db.refresh(work)
    return work


def test_delete_work_returns_success():
    db = database.SessionLocal()
    try:
        user = db.query(User).filter_by(username="owner").first()
        work = _make_work(db, user.id)
        resp = client.delete(f"/api/works/{work.id}")
        assert resp.status_code == 200
        assert resp.json() == {"success": True}
        assert db.query(CanvasWork).filter_by(id=work.id).first() is None
    finally:
        db.close()


def test_delete_work_cascades_nodes_and_edges():
    db = database.SessionLocal()
    try:
        user = db.query(User).filter_by(username="owner").first()
        work = _make_work(db, user.id)
        n1 = Node(work_id=work.id, type="character", title="角色A")
        n2 = Node(work_id=work.id, type="chapter", title="第一章")
        db.add_all([n1, n2])
        db.commit()
        db.refresh(n1)
        db.refresh(n2)
        edge = Edge(work_id=work.id, source_id=n1.id, target_id=n2.id, edge_type="登场")
        db.add(edge)
        db.commit()

        resp = client.delete(f"/api/works/{work.id}")
        assert resp.status_code == 200
        assert db.query(Node).filter_by(work_id=work.id).count() == 0
        assert db.query(Edge).filter_by(work_id=work.id).count() == 0
    finally:
        db.close()


def test_delete_work_not_found():
    resp = client.delete("/api/works/nonexistent-id")
    assert resp.status_code == 404


def test_delete_work_forbidden_for_other_user(mock_auth):
    db = database.SessionLocal()
    try:
        other = mock_auth["other"]
        work = _make_work(db, other.id, title="他人作品")
        resp = client.delete(f"/api/works/{work.id}")
        assert resp.status_code == 404
        assert db.query(CanvasWork).filter_by(id=work.id).first() is not None
    finally:
        db.close()
