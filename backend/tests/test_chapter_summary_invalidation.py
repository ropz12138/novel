"""章节正文变更后清空 chapters.summary — TDD。"""
import importlib
import json
import pytest

import database
from models.chapter import Chapter
from models.node import Node
from models.user import User
from models.work import CanvasWork
from services.chapter_history_service import clear_chapter_summary_on_content_change
from routers.node import create_node as create_node_route, update_node as update_node_route
from schemas.node import NodeCreate, NodeUpdate

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


def test_update_node_content_synchronizes_chapter_row(db_session):
    work = _make_work(db_session)
    node = Node(sort_order=0, work_id=work.id, type="chapter", title="第1章", content="旧正文")
    db_session.add(node)
    db_session.commit()
    row = Chapter(work_id=work.id, node_id=node.id, title=node.title, content="旧正文", summary="旧摘要")
    db_session.add(row)
    db_session.commit()

    result = json.loads(nt._update_node_sync(node.id, content="新正文"))

    assert result["success"] is True
    db_session.refresh(node)
    db_session.refresh(row)
    assert node.content == row.content == "新正文"
    assert row.summary == ""


def test_frontend_node_update_uses_same_chapter_content_path(db_session):
    work = _make_work(db_session)
    user = db_session.get(User, work.user_id)
    node = Node(sort_order=0, work_id=work.id, type="chapter", title="第1章", content="旧正文")
    db_session.add(node)
    db_session.commit()
    row = Chapter(work_id=work.id, node_id=node.id, title=node.title, content="旧正文", summary="旧摘要")
    db_session.add(row)
    db_session.commit()

    update_node_route(node.id, NodeUpdate(content="前端修改正文"), db_session, user)

    db_session.refresh(node)
    db_session.refresh(row)
    assert node.content == row.content == "前端修改正文"
    assert row.summary == ""


def test_agent_create_chapter_with_content_creates_chapter_row(db_session, monkeypatch):
    work = _make_work(db_session)
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)

    result = json.loads(nt._create_node_sync("chapter", "第1章", content="初始正文", sort_order=1))

    assert result["success"] is True
    chapter = db_session.query(Chapter).filter(Chapter.node_id == result["node"]["id"]).one()
    assert chapter.content == "初始正文"
    assert chapter.title == "第1章"


def test_agent_create_inserts_empty_node_before_writing_content(db_session, monkeypatch):
    from sqlalchemy import inspect
    from services import node_content_write_service as writer

    work = _make_work(db_session)
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    original_write = writer.write_node_content
    observed = []

    def checked_write(db, node, content, **kwargs):
        observed.append((inspect(node).persistent, node.content))
        return original_write(db, node, content, **kwargs)

    monkeypatch.setattr(writer, "write_node_content", checked_write)
    result = json.loads(nt._create_node_sync("chapter", "第1章", content="正文", sort_order=1))

    assert result["success"] is True
    assert observed == [(True, "")]


def test_frontend_create_chapter_with_content_creates_chapter_row(db_session):
    work = _make_work(db_session)
    user = db_session.get(User, work.user_id)

    node = create_node_route(work.id, NodeCreate(type="chapter", title="第1章", content="初始正文", sort_order=1), db_session, user)

    chapter = db_session.query(Chapter).filter(Chapter.node_id == node.id).one()
    assert chapter.content == "初始正文"
    assert chapter.title == "第1章"


def test_batch_create_chapter_with_content_creates_chapter_row(db_session, monkeypatch):
    work = _make_work(db_session)
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)

    result = json.loads(nt._batch_create_nodes_sync([
        {"node_type": "chapter", "title": "第1章", "content": "批量初稿", "sort_order": 1},
    ]))

    assert result["success"] is True
    chapter = db_session.query(Chapter).filter(Chapter.node_id == result["nodes"][0]["id"]).one()
    assert chapter.content == "批量初稿"


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


@pytest.mark.parametrize("marker", ["", "[[PLOT]]主角逃走了。[[/PLOT]]", "[[PLOT]]未闭合"])
def test_update_node_accepts_chapter_without_highlight_gate(db_session, marker):
    work = _make_work(db_session)
    node = Node(sort_order=0, work_id=work.id, type="chapter", title="第1章", content="短草稿")
    db_session.add(node)
    db_session.commit()

    weak_content = "正文铺陈。" * 160 + marker
    result = json.loads(nt._update_node_sync(node.id, content=weak_content))

    assert result["success"] is True
    assert "plot_highlight_validation" not in result
    db_session.refresh(node)
    assert node.content == weak_content


@pytest.mark.parametrize("marker", ["", "[[PLOT]]主角逃走了。[[/PLOT]]", "[[PLOT]]未闭合"])
def test_create_node_accepts_chapter_without_highlight_gate(db_session, monkeypatch, marker):
    work = _make_work(db_session)
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    content = "正文铺陈。" * 160 + marker
    result = json.loads(nt._create_node_sync("chapter", "新章节", content=content, sort_order=1))
    assert result["success"] is True
    assert "plot_highlight_validation" not in result
    assert db_session.get(Node, result["node"]["id"]).content == content
