"""插图文件下载接口测试 — TDD。"""
import pytest
from fastapi.testclient import TestClient

from main import app
import database
from routers.auth import get_current_user
from models.user import User
from models.work import CanvasWork
from models.node import Node
from models.chapter_illustration import ChapterIllustration

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="illus", email="illus@t.t", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def test_get_illustration_returns_png(tmp_path, monkeypatch):
    db = database.SessionLocal()
    try:
        user = db.query(User).filter(User.username == "illus").one()
        work = CanvasWork(user_id=user.id, title="w")
        db.add(work)
        db.commit()
        node = Node(work_id=work.id, type="chapter", title="章", content="正文", layer=3)
        db.add(node)
        db.commit()

        png_path = tmp_path / "test.png"
        raw = b"\x89PNG\r\n\x1a\n" + b"illus-bytes"
        png_path.write_bytes(raw)

        illus = ChapterIllustration(
            work_id=work.id,
            node_id=node.id,
            file_path=str(png_path),
            prompt="test",
            insert_after_paragraph=1,
        )
        db.add(illus)
        db.commit()
        db.refresh(illus)

        resp = client.get(f"/api/illustrations/{illus.id}")
        assert resp.status_code == 200
        assert resp.content == raw
        assert "image/png" in resp.headers.get("content-type", "")
    finally:
        db.close()


def test_get_illustration_not_found():
    resp = client.get("/api/illustrations/nonexistent-id")
    assert resp.status_code == 404
