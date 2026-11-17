"""REST PUT /api/nodes/{id} 不再接受或保留 chapter_elements。

传入 chapter_elements 会被忽略；已有 extra_data.chapter_elements 会在更新时被清掉，其它字段保留。
"""
import pytest
from fastapi.testclient import TestClient

from main import app
import database
from routers.auth import get_current_user
from models.user import User
from models.work import CanvasWork
from models.node import Node

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="chapter-api", email="chapter-api@test.dev", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def _make_chapter(db, user_id, extra_data=None):
    work = CanvasWork(user_id=user_id, title="w")
    db.add(work)
    db.commit()
    db.refresh(work)
    node = Node(sort_order=0,
        work_id=work.id,
        type="chapter",
        title="第一章",
        content="草稿",
        extra_data=extra_data or {},
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def test_put_chapter_elements_is_ignored_and_stripped(mock_auth):
    db = database.SessionLocal()
    try:
        node = _make_chapter(db, mock_auth.id, extra_data={
            "last_generation": {"sync_evaluations": [{"passed": True}]},
            "chapter_elements": [{"id": "old", "title": "旧元素"}],
        })
        response = client.put(
            f"/api/nodes/{node.id}",
            json={
                "chapter_elements": [
                    {"title": "主角觉醒", "content": "林远感知时间异常"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "chapter_elements" not in (data.get("extra_data") or {})
        assert data["extra_data"]["last_generation"] == {"sync_evaluations": [{"passed": True}]}
        db.refresh(node)
        assert "chapter_elements" not in (node.extra_data or {})
    finally:
        db.close()


def test_put_without_chapter_elements_strips_existing(mock_auth):
    db = database.SessionLocal()
    try:
        node = _make_chapter(db, mock_auth.id, extra_data={
            "chapter_elements": [{"id": "keep", "title": "保留元素"}],
            "keep": 1,
        })
        response = client.put(
            f"/api/nodes/{node.id}",
            json={"title": "新标题"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["title"] == "新标题"
        assert "chapter_elements" not in (data.get("extra_data") or {})
        assert data["extra_data"]["keep"] == 1
    finally:
        db.close()


def test_put_chapter_elements_on_non_chapter_is_ignored(mock_auth):
    db = database.SessionLocal()
    try:
        work = CanvasWork(user_id=mock_auth.id, title="w")
        db.add(work)
        db.commit()
        db.refresh(work)
        node = Node(sort_order=0, work_id=work.id, type="note", title="笔记节点", extra_data={"keep": True})
        db.add(node)
        db.commit()
        db.refresh(node)

        response = client.put(
            f"/api/nodes/{node.id}",
            json={"chapter_elements": [{"title": "不该出现"}]},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "chapter_elements" not in (data.get("extra_data") or {})
        assert data["extra_data"]["keep"] is True
    finally:
        db.close()
