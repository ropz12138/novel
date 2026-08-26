import gzip
import hashlib
import json
from pathlib import Path

from models.research import ResearchContextEpoch
from models.user import User
from services import research_text_tools
from services.research_agent import (
    CompactResearchContextInput,
    CompactionContext,
    QueryArchivedEventsInput,
    _build_job_snapshot,
    _commit_context_compaction,
    _context_requires_compaction,
    _query_archived_events,
    _read_context_archive,
    add_research_event,
)


def _create_job(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(
        research_text_tools,
        "RESEARCH_ROOT",
        tmp_path / "research",
    )
    user = User(
        username="context-reader",
        email="context-reader@example.com",
        password_hash="not-used",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    created = research_text_tools.create_job_files(
        user.id,
        "novel.txt",
        "第一章\n正文".encode(),
    )
    return created["job_id"], created["version_id"]


def test_context_compaction_archives_and_starts_new_epoch(
    db_session,
    monkeypatch,
    tmp_path,
):
    job_id, version_id = _create_job(db_session, monkeypatch, tmp_path)
    old_event = add_research_event(job_id, "tool_result", "旧上下文中的关键事实")
    before = _build_job_snapshot(job_id)
    context = CompactionContext(
        system_prompt="system",
        snapshot=before.text,
        tool_schemas_text="[]",
        model_name="test-model",
        estimated_input_tokens=100_000,
        compact_through_sequence=old_event.sequence,
        source_event_start=1,
        previous_epoch_id=None,
    )

    result = _commit_context_compaction(
        job_id,
        context,
        stage="持续阅读",
        completed_work=["已完成格式检查"],
        confirmed_findings=["开篇直接进入冲突"],
        tentative_findings=[],
        open_questions=["中段节奏是否稳定"],
        operational_lessons=["章节路径必须来自 manifest"],
        next_actions=["读取下一批章节"],
        citations=[{
            "source_type": "event",
            "source_id": str(old_event.sequence),
            "note": "支持开篇判断",
        }, {
            "source_type": "version",
            "source_id": version_id,
            "note": "当前文本版本",
        }],
        compact_through_sequence=old_event.sequence,
    )

    db_session.expire_all()
    epoch = db_session.query(ResearchContextEpoch).one()
    archive = Path(epoch.archive_path)
    assert result["success"] is True
    assert archive.is_file()
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == epoch.archive_sha256
    archived_payload = json.loads(gzip.decompress(archive.read_bytes()))
    assert archived_payload["rendered_request"]["snapshot"] == before.text

    new_event = add_research_event(job_id, "agent", "水位线后的新进展")
    after = _build_job_snapshot(job_id)
    assert epoch.id in after.text
    assert "开篇直接进入冲突" in after.text
    assert "旧上下文中的关键事实" not in after.text
    assert "水位线后的新进展" in after.text
    assert after.compact_through_sequence == old_event.sequence
    assert after.max_event_sequence == new_event.sequence

    queried = _query_archived_events(job_id, query="关键事实")
    assert [item["sequence"] for item in queried["events"]] == [old_event.sequence]
    assert _query_archived_events(
        job_id,
        start_sequence=new_event.sequence,
    )["events"] == []
    archive_page = _read_context_archive(job_id, max_chars=80_000)
    page_payload = json.loads(archive_page["content"])
    assert page_payload["rendered_request"]["snapshot"] == before.text


def test_compaction_threshold_and_array_schemas_are_direct_arrays():
    assert _context_requires_compaction(103_200, 128_000) is True
    assert _context_requires_compaction(103_199, 128_000) is False

    compact_schema = CompactResearchContextInput.model_json_schema()["properties"]
    for field in (
        "completed_work",
        "confirmed_findings",
        "tentative_findings",
        "open_questions",
        "operational_lessons",
        "next_actions",
        "citations",
    ):
        assert compact_schema[field]["type"] == "array"
        assert "anyOf" not in compact_schema[field]

    query_schema = QueryArchivedEventsInput.model_json_schema()["properties"]
    assert query_schema["event_types"]["type"] == "array"
    assert "anyOf" not in query_schema["event_types"]
