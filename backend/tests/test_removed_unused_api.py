"""已清理的闲置 REST 接口应返回 404。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

REMOVED_ROUTES = [
    "/api/works/chapters/get",
    "/api/works/characters/get",
    "/api/works/characters/tools/query",
    "/api/works/characters/tools/grep",
]


@pytest.mark.parametrize("path", REMOVED_ROUTES)
def test_removed_routes_not_registered(path):
    response = client.post(path, json={})
    assert response.status_code == 404, f"POST {path} should be removed"
