from fastapi.testclient import TestClient

from main import app
import database
from config import settings
from models.user import User

client = TestClient(app)


def test_health_check():
    response = client.post("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_registration_creates_user_role_with_gemini_and_no_fallback():
    response = client.post("/api/auth/register", json={
        "username": "new-user",
        "email": "new-user@example.com",
        "password": "secret123",
    })
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "user"

    with database.SessionLocal() as db:
        user = db.query(User).filter_by(email="new-user@example.com").one()
        assert user.role == "user"
        assert user.primary_model == settings.default_model == "gemini-3.8-flash-high"
        assert user.fallback_model == ""
