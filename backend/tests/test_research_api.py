import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from models.user import User
from routers.auth import get_current_user
from services import research_text_tools
from services.research_agent import research_agent_manager


def _add_indexed_cleaned_version(db_session, tmp_path, job_id):
    result = research_text_tools.create_cleaned_copy(job_id)
    from models.research import ResearchTextVersion
    version = db_session.query(ResearchTextVersion).filter_by(id=result["version_id"]).one()
    text = "第一章 开始\n正文A\n第二章 继续\n正文B"
    Path(version.file_path).write_text(text, encoding="utf-8")
    second_start = text.index("第二章")
    index_path = tmp_path / "chapters.json"
    index_path.write_text(json.dumps([
        {"type": "chapter", "number": 1, "title": "开始", "heading": "第一章 开始",
         "char_start": 0, "char_heading_end": len("第一章 开始"), "char_end": second_start},
        {"type": "chapter", "number": 2, "title": "继续", "heading": "第二章 继续",
         "char_start": second_start, "char_heading_end": second_start + len("第二章 继续"),
         "char_end": len(text)},
    ], ensure_ascii=False), encoding="utf-8")
    version.index_path = str(index_path)
    db_session.commit()
    return version


def test_upload_creates_work_without_starting_research(
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
            "/api/research/works?filename=example.txt",
            content="第一章 开始\n正文".encode("utf-8"),
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        assert started == []
        assert started_with_running_loop == []

        listed = client.get("/api/research/works")
        assert listed.status_code == 200
        assert listed.json()["works"][0]["id"] == job_id
        assert listed.json()["works"][0]["status"] == "ready"
        versions = client.get(f"/api/research/works/{job_id}/versions")
        assert versions.status_code == 200
        assert versions.json()["versions"][0]["kind"] == "raw"
    finally:
        app.dependency_overrides.clear()


def test_research_chat_exposes_cleaning_and_version_tools():
    from services.research_chat import CHAT_TOOL_NAMES, build_research_chat_tools
    assert {
        "create_cleaned_copy", "transform_novel_text",
        "normalize_novel_sections", "edit_novel_text", "diff_novel_versions",
    } <= CHAT_TOOL_NAMES
    assert "respond_to_user" in {
        tool.name for tool in build_research_chat_tools("user-1", None)
    }


def test_research_chat_artifact_tool_requires_explicit_work_id():
    from services.research_chat import build_research_chat_tools
    tools = {tool.name: tool for tool in build_research_chat_tools("user-1", "work-1")}
    schema = tools["save_research_artifact"].args_schema.model_json_schema()
    assert "work_id" in schema["properties"]
    assert "work_id" in schema["required"]


def test_lists_existing_research_artifacts_for_owned_work(
    db_session, monkeypatch, tmp_path,
):
    monkeypatch.setattr(research_text_tools, "RESEARCH_ROOT", tmp_path / "research")
    user = User(username="artifact-reader", email="artifact-reader@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    created = research_text_tools.create_job_files(user.id, "作品.txt", "正文".encode())
    from models.research import ResearchArtifact
    db_session.add(ResearchArtifact(
        job_id=created["job_id"], artifact_type="technique_card",
        title="C01-开篇钩子", content="技法卡正文",
    ))
    db_session.commit()
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        response = TestClient(app).get(
            f"/api/research/works/{created['job_id']}/artifacts"
        )
        assert response.status_code == 200
        assert response.json()["artifacts"][0]["title"] == "C01-开篇钩子"
        assert response.json()["artifacts"][0]["content"] == "技法卡正文"
        library = TestClient(app).get("/api/research/library")
        assert library.status_code == 200
        assert library.json()["works"] == [{
            "id": created["job_id"],
            "original_filename": "作品.txt",
            "artifacts": [response.json()["artifacts"][0]],
        }]
    finally:
        app.dependency_overrides.clear()


def test_browses_and_references_one_chapter_from_cleaned_text(
    db_session, monkeypatch, tmp_path,
):
    monkeypatch.setattr(research_text_tools, "RESEARCH_ROOT", tmp_path / "research")
    user = User(username="chapter-reader", email="chapter-reader@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    created = research_text_tools.create_job_files(
        user.id, "分章小说.txt", "第一章 开始\n正文A\n第二章 继续\n正文B".encode(),
    )
    version = _add_indexed_cleaned_version(db_session, tmp_path, created["job_id"])

    async def fake_reply(session_id):
        return "章节分析"

    from services.research_chat import research_chat_service
    monkeypatch.setattr(research_chat_service, "reply", fake_reply)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app)
        chapters = client.get(
            f"/api/research/works/{created['job_id']}/versions/{version.id}/chapters"
        )
        assert chapters.status_code == 200
        assert [row["heading"] for row in chapters.json()["chapters"]] == [
            "第一章 开始", "第二章 继续",
        ]
        chapter = client.get(
            f"/api/research/works/{created['job_id']}/versions/{version.id}/chapters/1"
        )
        assert chapter.status_code == 200
        assert chapter.json()["content"] == "第二章 继续\n正文B"

        session_id = client.post("/api/research/sessions", json={}).json()["id"]
        sent = client.post(
            f"/api/research/sessions/{session_id}/messages",
            json={"message": "分析这一章", "chapter_version_id": version.id,
                  "chapter_index": 1},
        )
        assert sent.status_code == 200
        reference = sent.json()["user_message"]["chapter_reference"]
        assert reference["heading"] == "第二章 继续"
        assert reference["work_id"] == created["job_id"]
    finally:
        app.dependency_overrides.clear()


def test_sessions_are_independent_and_each_message_can_reference_a_work(
    db_session, monkeypatch, tmp_path,
):
    monkeypatch.setattr(research_text_tools, "RESEARCH_ROOT", tmp_path / "research")
    user = User(username="chat-reader", email="chat-reader@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    async def fake_reply(session_id):
        return f"answer-for-{session_id}"

    from services.research_chat import research_chat_service
    monkeypatch.setattr(research_chat_service, "reply", fake_reply)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app)
        uploaded = client.post(
            "/api/research/works?filename=example.txt",
            content="第一章\n正文".encode(),
            headers={"content-type": "application/octet-stream"},
        ).json()
        first = client.post("/api/research/sessions", json={}).json()
        second = client.post("/api/research/sessions", json={}).json()
        assert first["id"] != second["id"]
        assert "work_id" not in first

        sent = client.post(
            f"/api/research/sessions/{first['id']}/messages",
            json={"message": "分析开篇", "work_id": uploaded["job_id"]},
        )
        assert sent.status_code == 200
        detail = client.get(f"/api/research/sessions/{first['id']}").json()
        assert detail["messages"][0]["referenced_works"] == [
            {"id": uploaded["job_id"], "filename": "example.txt"}
        ]
        assert detail["messages"][1]["content"] == f"answer-for-{first['id']}"
        assert client.get(f"/api/research/sessions/{second['id']}").json()["messages"] == []
    finally:
        app.dependency_overrides.clear()


def test_legacy_research_events_migrate_to_one_independent_session(
    db_session, monkeypatch, tmp_path,
):
    monkeypatch.setattr(research_text_tools, "RESEARCH_ROOT", tmp_path / "research")
    user = User(username="legacy-reader", email="legacy-reader@example.com", password_hash="x")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    created = research_text_tools.create_job_files(
        user.id, "旧小说.txt", "第一章\n正文".encode(),
    )

    from models.research import ResearchEvent, ResearchMessage, ResearchSession
    job_id = created["job_id"]
    db_session.add_all([
        ResearchEvent(job_id=job_id, sequence=1, event_type="tool_call", content="内部工具"),
        ResearchEvent(job_id=job_id, sequence=2, event_type="instruction", content="分析主角"),
        ResearchEvent(job_id=job_id, sequence=3, event_type="agent", content="主角分析结果"),
    ])
    db_session.commit()

    from services.research_chat import migrate_legacy_research_conversations
    first_count = migrate_legacy_research_conversations()
    second_count = migrate_legacy_research_conversations()
    assert first_count == 1
    assert second_count == 0

    session = db_session.query(ResearchSession).one()
    assert session.title == "《旧小说》研究记录"
    assert not hasattr(session, "work_id")
    messages = (db_session.query(ResearchMessage)
                .filter_by(session_id=session.id)
                .order_by(ResearchMessage.sequence).all())
    assert [(row.role, row.content) for row in messages] == [
        ("user", "分析主角"), ("assistant", "主角分析结果"),
    ]
    assert messages[0].work_references[0].work_id == job_id
    assert messages[1].work_references == []
