"""画布截图上传接口测试 — TDD。

POST /api/works/{work_id}/canvas/render
前端把 ReactFlow 截图(base64)上传，后端落盘缓存，供多模态评估工具读取。
"""
import base64

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import database
from app.routers.auth import get_current_user
from app.models.user import User
from app.services.agents.tools import canvas_evaluate

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth():
    db = database.SessionLocal()
    try:
        user = User(username="t", email="t@t.t", password_hash="x")
        db.add(user)
        db.commit()
        db.refresh(user)
        app.dependency_overrides[get_current_user] = lambda: user
        yield user
        app.dependency_overrides.pop(get_current_user, None)
    finally:
        db.close()


def test_upload_canvas_render_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(canvas_evaluate, "RENDER_DIR", tmp_path)
    raw = b'\x89PNG\r\n\x1a\n' + b'fake-screenshot'
    resp = client.post(
        "/api/works/wk-1/canvas/render",
        json={"image": base64.b64encode(raw).decode()},
    )
    assert resp.status_code == 200
    out = tmp_path / "wk-1.png"
    assert out.exists()
    assert out.read_bytes() == raw


def test_upload_overwrites_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(canvas_evaluate, "RENDER_DIR", tmp_path)
    client.post("/api/works/wk-2/canvas/render",
                json={"image": base64.b64encode(b'old').decode()})
    client.post("/api/works/wk-2/canvas/render",
                json={"image": base64.b64encode(b'new').decode()})
    assert (tmp_path / "wk-2.png").read_bytes() == b'new'
