"""write_chapter 上一章正文注入测试 — TDD。

agent 调 write_chapter 时传 prev_chapter_node_id（上一章节点ID），
工具内部读取该节点正文注入提示词，保证章节连贯。章节之间无需连线。
"""
import importlib

from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node

ct = importlib.import_module("app.services.agents.tools.chapter_tools")


# ---------- _build_write_chapter_messages：前文段注入 ----------

def test_build_messages_includes_prev_chapter_section():
    msgs = ct._build_write_chapter_messages(
        user_directive="写第二章",
        context="【大纲】...",
        extra="",
        global_context="",
        prev_chapter="林远走出图书馆，丧尸围拢过来……",
    )
    human = msgs[1].content
    assert "上一章正文" in human
    assert "林远走出图书馆" in human


def test_build_messages_omits_prev_section_when_empty():
    msgs = ct._build_write_chapter_messages(
        user_directive="写第一章",
        context="【大纲】...",
        extra="",
        prev_chapter="",
    )
    human = msgs[1].content
    assert "上一章正文" not in human


# ---------- _read_prev_chapter_content：按节点ID读取上一章正文 ----------

def _make_work(db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    return work


def test_read_prev_chapter_returns_content_by_id():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        ch1 = Node(work_id=work.id, type="chapter", title="第一章", content="第一章正文：林远觉醒……")
        db.add(ch1)
        db.commit()
        assert ct._read_prev_chapter_content(db, ch1.id) == "第一章正文：林远觉醒……"
    finally:
        db.close()


def test_read_prev_chapter_empty_when_no_id():
    db = database.SessionLocal()
    try:
        assert ct._read_prev_chapter_content(db, None) == ""
        assert ct._read_prev_chapter_content(db, "") == ""
    finally:
        db.close()


def test_read_prev_chapter_empty_when_node_missing():
    db = database.SessionLocal()
    try:
        assert ct._read_prev_chapter_content(db, "不存在的id") == ""
    finally:
        db.close()

