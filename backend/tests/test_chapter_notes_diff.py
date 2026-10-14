"""章节笔记与正文使用同一套段落 diff、基线和确认。"""
import asyncio
import hashlib
import json

from models.chapter import Chapter
from models.user import User
from models.node import Node
from models.work import CanvasWork
from routers.node import NotesDiffDecision, decide_notes_diff, list_notes_diffs, update_node as update_node_route
from schemas.node import NodeUpdate
import pytest
from services.agents.supervisor import set_context
from services.agents.tools import workflow_skill_tools as tools
from services.supervisor_event_persist import persist_supervisor_event


@pytest.fixture
def chapters(db_session):
    user = User(username="notes-diff", email="notes-diff@test.local", password_hash="x")
    db_session.add(user)
    db_session.flush()
    work = CanvasWork(user_id=user.id, title="笔记 diff")
    db_session.add(work)
    db_session.flush()
    nodes = [Node(work_id=work.id, type="chapter", title=f"第{i}章", sort_order=i,
                  content=f"正文{i}：晶核数量{i}。") for i in range(1, 3)]
    db_session.add_all(nodes)
    db_session.flush()
    db_session.commit()
    set_context({"work_id": work.id, "session_id": "new-session"})
    yield nodes
    set_context({})


def invoke(name, **kwargs):
    return json.loads(asyncio.run(getattr(tools, name).ainvoke(kwargs)))


def test_saving_notes_emits_paragraph_diff(chapters):
    node = chapters[0]
    events = []

    async def emit(name, data):
        events.append((name, data))

    set_context({"work_id": node.work_id, "emit": emit})
    invoke(
        "save_chapter_notes",
        chapter_node_id=node.id,
        notes="事实：旧晶核。\n\n作者要求：保留伤势。",
        expected_content_sha256=hashlib.sha256(node.content.encode()).hexdigest(),
    )
    invoke(
        "save_chapter_notes",
        chapter_node_id=node.id,
        notes="事实：新晶核。\n\n作者要求：保留伤势。",
        expected_content_sha256=hashlib.sha256(node.content.encode()).hexdigest(),
        expected_notes_sha256=hashlib.sha256("事实：旧晶核。\n\n作者要求：保留伤势。".encode()).hexdigest(),
    )

    diff_events = [data for name, data in events if name == "chapter_notes_diff"]
    assert len(diff_events) == 2
    second = diff_events[1]
    assert second["chapter_node_id"] == node.id
    assert second["original_notes"] == "事实：旧晶核。\n\n作者要求：保留伤势。"
    assert second["current_notes"] == "事实：新晶核。\n\n作者要求：保留伤势。"
    assert second["diff"]["hunks"] == [{
        "type": "replace",
        "paragraph_index": 1,
        "old_text": "事实：旧晶核。",
        "new_text": "事实：新晶核。",
    }]


def test_notes_diff_persists_baseline_and_reject_restores_notes(chapters, db_session):
    node = chapters[0]
    user = db_session.query(User).one()
    db_session.add(Chapter(work_id=node.work_id, node_id=node.id, notes="事实：旧晶核。"))
    db_session.commit()
    events = []

    async def emit(name, data):
        events.append((name, data))

    set_context({"work_id": node.work_id, "session_id": "notes-diff-session", "emit": emit})
    from models.session import SupervisorSession
    db_session.add(SupervisorSession(
        id="notes-diff-session", user_id=user.id, work_id=node.work_id, title="笔记", status="idle",
    ))
    db_session.commit()
    invoke(
        "save_chapter_notes",
        chapter_node_id=node.id,
        notes="事实：新晶核。",
        expected_content_sha256=hashlib.sha256(node.content.encode()).hexdigest(),
        expected_notes_sha256=hashlib.sha256("事实：旧晶核。".encode()).hexdigest(),
    )
    payload = next(data for name, data in events if name == "chapter_notes_diff")
    assert persist_supervisor_event(db_session, "notes-diff-session", "chapter_notes_diff", payload)

    rows = list_notes_diffs(node.work_id, db_session, user)
    assert rows == [{
        "node_id": node.id,
        "original_notes": "事实：旧晶核。",
        "current_notes": "事实：新晶核。",
    }]

    result = decide_notes_diff(node.id, NotesDiffDecision(
        expected_notes="事实：新晶核。",
        expected_baseline="事实：旧晶核。",
        baseline_notes="事实：旧晶核。",
        current_notes="事实：旧晶核。",
    ), db_session, user)
    db_session.expire_all()
    assert result["current_notes"] == "事实：旧晶核。"
    assert db_session.query(Chapter).filter_by(node_id=node.id).one().notes == "事实：旧晶核。"
    assert list_notes_diffs(node.work_id, db_session, user) == []


def test_manual_notes_edit_folds_into_pending_baseline(chapters, db_session):
    node = chapters[0]
    user = db_session.query(User).one()
    db_session.add(Chapter(work_id=node.work_id, node_id=node.id, notes="事实：旧晶核。"))
    db_session.commit()
    events = []

    async def emit(name, data):
        events.append((name, data))

    set_context({"work_id": node.work_id, "session_id": "notes-manual-session", "emit": emit})
    from models.session import SupervisorSession
    db_session.add(SupervisorSession(
        id="notes-manual-session", user_id=user.id, work_id=node.work_id, title="笔记", status="idle",
    ))
    db_session.commit()
    invoke(
        "save_chapter_notes",
        chapter_node_id=node.id,
        notes="事实：新晶核。",
        expected_content_sha256=hashlib.sha256(node.content.encode()).hexdigest(),
        expected_notes_sha256=hashlib.sha256("事实：旧晶核。".encode()).hexdigest(),
    )
    payload = next(data for name, data in events if name == "chapter_notes_diff")
    persist_supervisor_event(db_session, "notes-manual-session", "chapter_notes_diff", payload)

    update_node_route(node.id, NodeUpdate(notes="事实：手改。"), db_session, user)
    rows = list_notes_diffs(node.work_id, db_session, user)
    assert rows == []
    assert db_session.query(Chapter).filter_by(node_id=node.id).one().notes == "事实：手改。"
