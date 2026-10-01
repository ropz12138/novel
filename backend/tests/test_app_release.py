from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_app_release_returns_mobile_config(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "mobile_version_name", "1.1.8")
    monkeypatch.setattr(settings, "mobile_version_code", 11)
    monkeypatch.setattr(settings, "mobile_download_url", "/novel/novel.apk")
    response = client.get("/api/app/release")

    assert response.status_code == 200
    assert response.json() == {
        "version_name": "1.1.8",
        "version_code": 11,
        "download_url": "/novel/novel.apk",
    }
