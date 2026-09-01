"""章节正文变更后清空 chapters.summary — TDD。"""
import importlib
import json

import database
from models.chapter import Chapter
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.chapter_history_service import clear_chapter_summary_on_content_change

nt = importlib.import_module("services.agents.tools.node_tools")


def _make_work(db):
    user = User(username="sum-inv", email="sum-inv@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    return work


def test_clear_chapter_summary_clears_existing_summary(db_session):
    work = _make_work(db_session)
    node = Node(sort_order=0, work_id=work.id, type="chapter", title="第1章", content="旧正文")
    db_session.add(node)
    db_session.commit()
    row = Chapter(work_id=work.id, node_id=node.id, title=node.title, summary="旧评估摘要")
    db_session.add(row)
    db_session.commit()

    clear_chapter_summary_on_content_change(db_session, node)
    db_session.commit()
    db_session.refresh(row)

    assert row.summary == ""


def test_clear_chapter_summary_noop_for_non_chapter(db_session):
    work = _make_work(db_session)
    node = Node(sort_order=0, work_id=work.id, type="outline", title="大纲", content="内容")
    db_session.add(node)
    db_session.commit()

    clear_chapter_summary_on_content_change(db_session, node)
    db_session.commit()

    assert db_session.query(Chapter).count() == 0


def test_update_node_content_clears_chapter_summary(db_session):
    work = _make_work(db_session)
    node = Node(sort_order=0, work_id=work.id, type="chapter", title="第1章", content="旧正文")
    db_session.add(node)
    db_session.commit()
    row = Chapter(work_id=work.id, node_id=node.id, title=node.title, summary="旧摘要")
    db_session.add(row)
    db_session.commit()

    result = json.loads(nt._update_node_sync(node.id, content="手改后的正文"))
    assert result["success"] is True

    db_session.refresh(row)
    assert row.summary == ""


def test_update_node_title_only_keeps_summary(db_session):
    work = _make_work(db_session)
    node = Node(sort_order=0, work_id=work.id, type="chapter", title="第1章", content="正文")
    db_session.add(node)
    db_session.commit()
    row = Chapter(work_id=work.id, node_id=node.id, title=node.title, summary="保留摘要")
    db_session.add(row)
    db_session.commit()

    result = json.loads(nt._update_node_sync(node.id, title="第1章：新标题"))
    assert result["success"] is True

    db_session.refresh(row)
    assert row.summary == "保留摘要"


def test_update_node_rejects_long_chapter_with_insufficient_highlights(db_session):
    work = _make_work(db_session)
    node = Node(sort_order=0, work_id=work.id, type="chapter", title="第1章", content="短草稿")
    db_session.add(node)
    db_session.commit()

    weak_content = "正文铺陈。" * 160 + "[[PLOT]]主角逃走了。[[/PLOT]]"
    result = json.loads(nt._update_node_sync(node.id, content=weak_content))

    assert result["success"] is False
    assert result["plot_highlight_validation"]["valid"] is False
    assert any(
        "数量不足" in error
        for error in result["plot_highlight_validation"]["errors"]
    )
    db_session.refresh(node)
    assert node.content == "短草稿"
