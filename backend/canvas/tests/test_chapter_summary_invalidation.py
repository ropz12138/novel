"""章节正文变更后清空 chapters.summary — TDD。"""
import asyncio
import importlib
import json

from langchain_core.messages import AIMessage

from app import database
from app.models.chapter import Chapter
from app.models.node import Node
from app.models.user import User
from app.models.work import CanvasWork
from app.services.chapter_history_service import clear_chapter_summary_on_content_change

ct = importlib.import_module("app.services.agents.tools.chapter_tools")
nt = importlib.import_module("app.services.agents.tools.node_tools")
llm_mod = importlib.import_module("app.services.agents.llm")


class FakeLLM:
    def __init__(self, response):
        self.response = response

    async def ainvoke(self, messages, config=None, **kwargs):
        return self.response

    async def astream(self, messages, config=None, **kwargs):
        yield self.response


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
    node = Node(work_id=work.id, type="chapter", title="第1章", content="旧正文")
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
    node = Node(work_id=work.id, type="outline", title="大纲", content="内容")
    db_session.add(node)
    db_session.commit()

    clear_chapter_summary_on_content_change(db_session, node)
    db_session.commit()

    assert db_session.query(Chapter).count() == 0


def test_write_chapter_clears_existing_summary(monkeypatch, db_session):
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM(AIMessage(content="新正文")),
    )
    work = _make_work(db_session)
    node = Node(work_id=work.id, type="chapter", title="第1章", content="旧正文")
    db_session.add(node)
    db_session.commit()
    row = Chapter(work_id=work.id, node_id=node.id, title=node.title, summary="待清空摘要")
    db_session.add(row)
    db_session.commit()

    result = json.loads(asyncio.run(
        ct._write_chapter_coroutine(node.id, "重写本章", "上下文", "")
    ))
    assert result["success"] is True

    db_session.refresh(row)
    assert row.summary == ""


def test_update_node_content_clears_chapter_summary(db_session):
    work = _make_work(db_session)
    node = Node(work_id=work.id, type="chapter", title="第1章", content="旧正文")
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
    node = Node(work_id=work.id, type="chapter", title="第1章", content="正文")
    db_session.add(node)
    db_session.commit()
    row = Chapter(work_id=work.id, node_id=node.id, title=node.title, summary="保留摘要")
    db_session.add(row)
    db_session.commit()

    result = json.loads(nt._update_node_sync(node.id, title="第1章：新标题"))
    assert result["success"] is True

    db_session.refresh(row)
    assert row.summary == "保留摘要"


def test_edit_chapter_content_clears_existing_summary(monkeypatch, db_session):
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM(AIMessage(content='{"edits":[{"type":"replace","paragraph_index":1,"old_text":"旧","new_text":"新"}]}')),
    )
    work = _make_work(db_session)
    node = Node(work_id=work.id, type="chapter", title="第1章", content="旧")
    db_session.add(node)
    db_session.commit()
    row = Chapter(work_id=work.id, node_id=node.id, title=node.title, summary="待清空摘要")
    db_session.add(row)
    db_session.commit()

    result = json.loads(asyncio.run(
        ct._edit_chapter_content_coroutine(node.id, "改一下", "")
    ))
    assert result["success"] is True

    db_session.refresh(row)
    assert row.summary == ""
