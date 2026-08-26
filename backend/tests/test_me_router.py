"""用户模型偏好 API 测试 — TDD。

GET  /api/me/models        → 可用模型列表 + 全局默认主/备
GET  /api/me/model-pref    → 当前用户的主/备模型偏好（未设为 null）
PUT  /api/me/model-pref    → 更新主/备偏好；校验：必须属于可用模型、主备不能相同
"""
import pytest
from fastapi.testclient import TestClient

from main import app
import database
from config import settings
from routers.auth import get_current_user
from models.user import User

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_auth():
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


def test_get_models_returns_available_and_defaults():
    resp = client.get("/api/me/models")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["available_models"]) == set(settings.available_models)
    assert data["default_primary"] == settings.default_model
    assert data["default_fallback"] == settings.fallback_model


def test_get_model_pref_defaults_null(mock_auth):
    resp = client.get("/api/me/model-pref")
    assert resp.status_code == 200
    data = resp.json()
    assert data["primary"] is None
    assert data["fallback"] is None


def test_put_model_pref_persists(mock_auth):
    a_model = settings.available_models[0]
    b_model = settings.available_models[1]
    resp = client.put("/api/me/model-pref", json={"primary": a_model, "fallback": b_model})
    assert resp.status_code == 200
    assert resp.json()["primary"] == a_model
    assert resp.json()["fallback"] == b_model

    # 再次 GET 应拿到持久化的值
    got = client.get("/api/me/model-pref").json()
    assert got["primary"] == a_model
    assert got["fallback"] == b_model


def test_put_model_pref_rejects_unknown_model(mock_auth):
    resp = client.put("/api/me/model-pref", json={"primary": "not-a-real-model"})
    assert resp.status_code == 400


def test_put_model_pref_rejects_primary_equals_fallback(mock_auth):
    m = settings.available_models[0]
    resp = client.put("/api/me/model-pref", json={"primary": m, "fallback": m})
    assert resp.status_code == 400


def test_put_model_pref_allows_clearing_to_null(mock_auth):
    m = settings.available_models[0]
    # 先设一个主模型
    client.put("/api/me/model-pref", json={"primary": m, "fallback": None})
    # 再清空（回退到全局默认）
    resp = client.put("/api/me/model-pref", json={"primary": None, "fallback": None})
    assert resp.status_code == 200
    assert resp.json()["primary"] is None
    assert resp.json()["fallback"] is None
