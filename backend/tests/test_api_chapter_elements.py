"""REST PUT /api/nodes/{id} 的 chapter_elements 安全合并 — TDD。

- chapter 节点可通过 PUT 的 chapter_elements 字段更新本章元素
- 更新只覆盖 extra_data.chapter_elements，保留 last_generation 等其它字段
- 非 chapter 节点拒绝 chapter_elements（与 agent 工具一致）
- 不带 chapter_elements 的 PUT 不影响现有元素（回归保护）
- 元素至少需 title 或 content，否则 400
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
    node = Node(
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


def test_put_chapter_elements_updates_chapter_node(mock_auth):
    db = database.SessionLocal()
    try:
        node = _make_chapter(db, mock_auth.id)
        response = client.put(
            f"/api/nodes/{node.id}",
            json={
                "chapter_elements": [
                    {"title": "主角觉醒", "content": "林远感知时间异常"},
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["extra_data"]["chapter_elements"][0]["title"] == "主角觉醒"
        assert data["extra_data"]["chapter_elements"][0]["content"] == "林远感知时间异常"
    finally:
        db.close()


def test_put_chapter_elements_preserves_other_extra_data(mock_auth):
    db = database.SessionLocal()
    try:
        node = _make_chapter(db, mock_auth.id, extra_data={
            "last_generation": {"sync_evaluations": [{"passed": True}]},
            "chapter_elements": [{"id": "old", "title": "旧元素"}],
        })
        response = client.put(
            f"/api/nodes/{node.id}",
            json={"chapter_elements": [{"title": "新元素"}]},
        )
        assert response.status_code == 200
        data = response.json()
        # chapter_elements 被替换
        assert len(data["extra_data"]["chapter_elements"]) == 1
        assert data["extra_data"]["chapter_elements"][0]["title"] == "新元素"
        # last_generation 必须保留
        assert data["extra_data"]["last_generation"] == {"sync_evaluations": [{"passed": True}]}
    finally:
        db.close()


def test_put_chapter_elements_rejects_non_chapter_node(mock_auth):
    db = database.SessionLocal()
    try:
        work = CanvasWork(user_id=mock_auth.id, title="w")
        db.add(work)
        db.commit()
        db.refresh(work)
        node = Node(work_id=work.id, type="plot", title="情节节点")
        db.add(node)
        db.commit()
        db.refresh(node)

        response = client.put(
            f"/api/nodes/{node.id}",
            json={"chapter_elements": [{"title": "不该出现"}]},
        )
        assert response.status_code == 400
        assert "chapter" in response.json()["detail"].lower()
    finally:
        db.close()


def test_put_without_chapter_elements_keeps_existing(mock_auth):
    db = database.SessionLocal()
    try:
        node = _make_chapter(db, mock_auth.id, extra_data={
            "chapter_elements": [{"id": "keep", "title": "保留元素"}],
        })
        response = client.put(
            f"/api/nodes/{node.id}",
            json={"title": "新标题"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "新标题"
        # 未传 chapter_elements，现有元素必须保持不变
        assert data["extra_data"]["chapter_elements"] == [{"id": "keep", "title": "保留元素"}]
    finally:
        db.close()


def test_put_chapter_elements_rejects_empty_item(mock_auth):
    db = database.SessionLocal()
    try:
        node = _make_chapter(db, mock_auth.id)
        response = client.put(
            f"/api/nodes/{node.id}",
            json={"chapter_elements": [{"title": "", "content": ""}]},
        )
        assert response.status_code == 400
    finally:
        db.close()
