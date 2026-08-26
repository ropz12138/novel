import asyncio

from fastapi.testclient import TestClient

from main import app
from models.user import User
from routers.auth import get_current_user
from services import research_text_tools
from services.research_agent import research_agent_manager


def test_upload_lists_pauses_and_continues_research_job(
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        research_text_tools,
        "RESEARCH_ROOT",
        tmp_path / "research",
    )
    user = User(
        username="reader",
        email="reader@example.com",
        password_hash="not-used",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    started = []
    started_with_running_loop = []

    def fake_start(job_id):
        started.append(job_id)
        started_with_running_loop.append(asyncio.get_running_loop().is_running())

    monkeypatch.setattr(research_agent_manager, "start", fake_start)

    async def fake_pause(job_id):
        from services.research_agent import _set_job_status
        _set_job_status(job_id, "paused", "已暂停")

    monkeypatch.setattr(research_agent_manager, "pause", fake_pause)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app)
        response = client.post(
            "/api/research/jobs?filename=example.txt",
            content="第一章 开始\n正文".encode("utf-8"),
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        assert started == [job_id]
        assert started_with_running_loop == [True]

        listed = client.get("/api/research/jobs")
        assert listed.status_code == 200
        assert listed.json()["jobs"][0]["id"] == job_id

        paused = client.post(f"/api/research/jobs/{job_id}/pause")
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"

        continued = client.post(
            f"/api/research/jobs/{job_id}/continue",
            json={"message": "重点分析开篇钩子"},
        )
        assert continued.status_code == 200
        assert continued.json()["status"] == "running"
        assert started == [job_id, job_id]
        assert started_with_running_loop == [True, True]

        events = client.get(f"/api/research/jobs/{job_id}/events")
        assert events.status_code == 200
        instruction_event = next(
            item
            for item in events.json()["events"]
            if item["event_type"] == "instruction"
        )
        assert instruction_event["content"] == "重点分析开篇钩子"

        incremental = client.get(
            f"/api/research/jobs/{job_id}/events",
            params={"after": instruction_event["sequence"]},
        )
        assert incremental.status_code == 200
        assert incremental.json()["events"] == []

        detail = client.get(f"/api/research/jobs/{job_id}")
        assert detail.status_code == 200
        assert len(detail.json()["versions"]) == 1
        assert detail.json()["versions"][0]["kind"] == "raw"
    finally:
        app.dependency_overrides.clear()
