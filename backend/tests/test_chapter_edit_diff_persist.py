"""chapter_edit_diff 事件持久化测试。"""
import uuid

import pytest

from models.session import SupervisorMessage, SupervisorSession
from services.supervisor_event_persist import (
    PERSISTABLE_DIFF_EVENTS,
    persist_supervisor_event,
)


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    """提供内存 SQLite DB session。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    from models.session import Base as SessionBase
    SessionBase.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    return TestSession()


@pytest.fixture()
def sample_session(db_session):
    """创建测试用 session。"""
    session = SupervisorSession(
        id=str(uuid.uuid4()),
        user_id="user-1",
        work_id="work-1",
        title="测试会话",
        stage="running",
        status="running",
    )
    db_session.add(session)
    db_session.commit()
    return session


def test_chapter_edit_diff_in_persistable_events():
    """chapter_edit_diff 应在可持久化事件集合中。"""
    assert "chapter_edit_diff" in PERSISTABLE_DIFF_EVENTS
    assert "node_content_diff" in PERSISTABLE_DIFF_EVENTS


def test_persist_chapter_edit_diff(db_session, sample_session):
    """chapter_edit_diff 事件应正确写入 supervisor_messages。"""
    session_id = sample_session.id
    data = {
        "chapter_node_id": "node-123",
        "title": "第一章 初遇",
        "word_count": 3200,
        "word_count_delta": 150,
        "diff": {
            "hunks": [
                {
                    "type": "replace",
                    "paragraph_index": 3,
                    "old_text": "他走在街上。",
                    "new_text": "他独自一人走在空旷的街道上，秋风卷起几片落叶。",
                },
                {
                    "type": "insert_after",
                    "paragraph_index": 5,
                    "old_text": "",
                    "new_text": "远处传来一阵悠扬的钟声。",
                },
            ],
            "summary": {
                "paragraphs_changed": 2,
                "chars_added": 35,
                "chars_removed": 8,
            },
        },
    }

    result = persist_supervisor_event(db_session, session_id, "chapter_edit_diff", data)
    assert result is True

    messages = (
        db_session.query(SupervisorMessage)
        .filter_by(session_id=session_id)
        .order_by(SupervisorMessage.sort_order)
        .all()
    )
    assert len(messages) == 1

    msg = messages[0]
    assert msg.role == "assistant"
    assert msg.content == ""
    assert msg.meta["type"] == "chapter_content_diff_card"

    card = msg.meta["chapterContentDiffCard"]
    assert card["chapter_node_id"] == "node-123"
    assert card["title"] == "第一章 初遇"
    assert card["word_count"] == 3200
    assert card["word_count_delta"] == 150
    assert len(card["hunks"]) == 2
    assert card["hunks"][0]["type"] == "replace"
    assert card["hunks"][0]["paragraph_index"] == 3
    assert card["hunks"][0]["old_text"] == "他走在街上。"
    assert card["hunks"][0]["new_text"] == "他独自一人走在空旷的街道上，秋风卷起几片落叶。"
    assert card["hunks"][1]["type"] == "insert_after"
    assert card["summary"]["paragraphs_changed"] == 2
    assert card["summary"]["chars_added"] == 35
    assert card["summary"]["chars_removed"] == 8


def test_persist_node_content_diff(db_session, sample_session):
    """node_content_diff 事件应正确写入 supervisor_messages。"""
    session_id = sample_session.id
    data = {
        "node_id": "node-style-1",
        "node_type": "style",
        "title": "风格说明",
        "text_count": 120,
        "text_count_delta": 12,
        "diff": {
            "hunks": [{
                "type": "replace",
                "paragraph_index": 1,
                "old_text": "旧风格",
                "new_text": "新风格",
            }],
            "summary": {"paragraphs_changed": 1, "chars_added": 3, "chars_removed": 3},
        },
    }

    result = persist_supervisor_event(db_session, session_id, "node_content_diff", data)
    assert result is True

    msg = db_session.query(SupervisorMessage).filter_by(session_id=session_id).one()
    card = msg.meta["chapterContentDiffCard"]
    assert card["node_id"] == "node-style-1"
    assert card["chapter_node_id"] == "node-style-1"
    assert card["node_type"] == "style"
    assert card["text_count"] == 120
    assert card["text_count_delta"] == 12
    assert card["hunks"][0]["new_text"] == "新风格"


def test_persist_chapter_edit_diff_with_empty_hunks(db_session, sample_session):
    """空 hunks 的 chapter_edit_diff 也能正常入库。"""
    session_id = sample_session.id
    data = {
        "chapter_node_id": "node-456",
        "title": "第二章",
        "word_count": 2800,
        "word_count_delta": 0,
        "diff": {
            "hunks": [],
            "summary": {"paragraphs_changed": 0, "chars_added": 0, "chars_removed": 0},
        },
    }

    result = persist_supervisor_event(db_session, session_id, "chapter_edit_diff", data)
    assert result is True

    messages = (
        db_session.query(SupervisorMessage)
        .filter_by(session_id=session_id)
        .all()
    )
    assert len(messages) == 1
    card = messages[0].meta["chapterContentDiffCard"]
    assert card["hunks"] == []
    assert card["summary"]["paragraphs_changed"] == 0


def test_persist_chapter_edit_diff_no_session(db_session):
    """不存在的 session_id 应返回 False。"""
    data = {
        "chapter_node_id": "node-123",
        "title": "第一章",
        "word_count": 3000,
        "word_count_delta": 0,
        "diff": {"hunks": [], "summary": {}},
    }

    result = persist_supervisor_event(db_session, "nonexistent", "chapter_edit_diff", data)
    assert result is False


def test_persist_chapter_edit_diff_missing_diff_key(db_session, sample_session):
    """data 中缺少 diff 字段时应使用空默认值。"""
    session_id = sample_session.id
    data = {
        "chapter_node_id": "node-789",
        "title": "第三章",
        "word_count": 2500,
        "word_count_delta": -200,
    }

    result = persist_supervisor_event(db_session, session_id, "chapter_edit_diff", data)
    assert result is True

    messages = (
        db_session.query(SupervisorMessage)
        .filter_by(session_id=session_id)
        .all()
    )
    assert len(messages) == 1
    card = messages[0].meta["chapterContentDiffCard"]
    assert card["hunks"] == []
    assert card["summary"] == {}


def test_persist_chapter_edit_diff_multiple_times(db_session, sample_session):
    """多次 chapter_edit_diff 应各自独立入库。"""
    session_id = sample_session.id

    for i in range(3):
        data = {
            "chapter_node_id": f"node-{i}",
            "title": f"第{i + 1}章",
            "word_count": 3000 + i * 100,
            "word_count_delta": i * 50,
            "diff": {
                "hunks": [{"type": "replace", "paragraph_index": 1, "old_text": "旧", "new_text": "新"}],
                "summary": {"paragraphs_changed": 1, "chars_added": 1, "chars_removed": 1},
            },
        }
        result = persist_supervisor_event(db_session, session_id, "chapter_edit_diff", data)
        assert result is True

    messages = (
        db_session.query(SupervisorMessage)
        .filter_by(session_id=session_id)
        .order_by(SupervisorMessage.sort_order)
        .all()
    )
    assert len(messages) == 3

    for i, msg in enumerate(messages):
        card = msg.meta["chapterContentDiffCard"]
        assert card["chapter_node_id"] == f"node-{i}"
        assert card["title"] == f"第{i + 1}章"
        assert card["word_count"] == 3000 + i * 100
