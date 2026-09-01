"""REST PUT /api/nodes/{id} 的 storylines 安全合并 — TDD。"""
import pytest
from fastapi.testclient import TestClient

from main import app
import database
from routers.auth import get_current_user
from models.user import User
from models.work import CanvasWork
from models.node import Node

client = TestClient(app)

SAMPLE_LINE = {
    "name": "心境线",
    "description": "暗线，人性与神性的拉锯。",
    "body": ["独善其身", "立下底线", "终章抉择"],
}


@pytest.fixture(autouse=True)
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="storylines-api", email="storylines-api@test.dev", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def _make_character(db, user_id, extra_data=None):
    work = CanvasWork(user_id=user_id, title="w")
    db.add(work)
    db.commit()
    db.refresh(work)
    node = Node(sort_order=0, 
        work_id=work.id,
        type="character",
        title="林川",
        content="人设",
        extra_data=extra_data or {},
        scope="global",
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def test_put_storylines_updates_character_node(mock_auth):
    db = database.SessionLocal()
    try:
        node = _make_character(db, mock_auth.id)
        response = client.put(
            f"/api/nodes/{node.id}",
            json={"storylines": [SAMPLE_LINE]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["extra_data"]["storylines"] == [SAMPLE_LINE]
    finally:
        db.close()


def test_put_storylines_preserves_other_extra_data(mock_auth):
    db = database.SessionLocal()
    try:
        node = _make_character(db, mock_auth.id, extra_data={
            "last_generation": {"ok": True},
            "storylines": [{"name": "旧", "description": "", "body": ["旧节点"]}],
        })
        response = client.put(
            f"/api/nodes/{node.id}",
            json={"storylines": [SAMPLE_LINE]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["extra_data"]["storylines"] == [SAMPLE_LINE]
        assert data["extra_data"]["last_generation"] == {"ok": True}
    finally:
        db.close()


def test_put_storylines_rejects_non_character_node(mock_auth):
    db = database.SessionLocal()
    try:
        work = CanvasWork(user_id=mock_auth.id, title="w")
        db.add(work)
        db.commit()
        db.refresh(work)
        node = Node(sort_order=0, work_id=work.id, type="chapter", title="第一章")
        db.add(node)
        db.commit()
        db.refresh(node)

        response = client.put(
            f"/api/nodes/{node.id}",
            json={"storylines": [SAMPLE_LINE]},
        )
        assert response.status_code == 400
        assert "character" in response.json()["detail"].lower()
    finally:
        db.close()


def test_put_without_storylines_keeps_existing(mock_auth):
    db = database.SessionLocal()
    try:
        node = _make_character(db, mock_auth.id, extra_data={
            "storylines": [SAMPLE_LINE],
        })
        response = client.put(
            f"/api/nodes/{node.id}",
            json={"title": "林川（主角）"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "林川（主角）"
        assert data["extra_data"]["storylines"] == [SAMPLE_LINE]
    finally:
        db.close()


def test_put_storylines_rejects_string_body(mock_auth):
    db = database.SessionLocal()
    try:
        node = _make_character(db, mock_auth.id)
        response = client.put(
            f"/api/nodes/{node.id}",
            json={"storylines": [{"name": "力量线", "description": "x", "body": "一整段"}]},
        )
        assert response.status_code == 400
    finally:
        db.close()
