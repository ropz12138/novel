"""所有业务接口均为 POST（RPC 风格）；旧 GET/PUT/DELETE 路径应不可用。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

LEGACY_ROUTES = [
    ("GET", "/health"),
    ("GET", "/api/works"),
    ("GET", "/api/works/w1"),
    ("PUT", "/api/works/w1/outline"),
    ("DELETE", "/api/works/w1"),
    ("GET", "/api/works/w1/chapters"),
    ("GET", "/api/works/w1/chapters/1"),
    ("GET", "/api/works/w1/chapters/1/intel"),
    ("DELETE", "/api/works/w1/chapters/last"),
    ("PUT", "/api/works/w1/chapters/1"),
    ("GET", "/api/works/w1/requirements-doc"),
    ("GET", "/api/works/w1/characters"),
    ("GET", "/api/works/w1/characters/c1"),
    ("POST", "/api/works/w1/characters"),
    ("PUT", "/api/works/w1/characters/c1"),
    ("DELETE", "/api/works/w1/characters/c1"),
    ("GET", "/api/supervisor-sessions"),
    ("GET", "/api/supervisor-sessions/s1/messages"),
    ("DELETE", "/api/supervisor-sessions/s1"),
]

POST_RPC_ROUTES = [
    "/health",
    "/api/works/list",
    "/api/works/get",
    "/api/works/delete",
    "/api/works/update-outline",
    "/api/works/chapters/list",
    "/api/works/chapters/intel",
    "/api/works/chapters/delete-last",
    "/api/works/chapters/update",
    "/api/works/requirements-doc/get",
    "/api/works/requirements-doc/update",
    "/api/works/characters/list",
    "/api/works/characters/create",
    "/api/works/characters/update",
    "/api/works/characters/delete",
    "/api/supervisor-sessions/list",
    "/api/supervisor-sessions/messages",
    "/api/supervisor-sessions/delete",
]


@pytest.mark.parametrize("method,path", LEGACY_ROUTES)
def test_legacy_routes_not_available(method, path):
    response = client.request(method, path, json={} if method != "GET" else None)
    assert response.status_code in (404, 405), f"{method} {path} => {response.status_code}"


def test_health_post_ok():
    response = client.post("/health", json={})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("path", POST_RPC_ROUTES[1:])
def test_rpc_routes_require_auth_or_valid_body(path):
    """未认证应 401；认证逻辑由集成测试覆盖，此处只验证路由存在且非 404。"""
    response = client.post(path, json={})
    assert response.status_code != 404, f"POST {path} should be registered"
