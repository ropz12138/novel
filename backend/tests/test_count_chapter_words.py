"""count_chapter_words 工具测试 — TDD。"""
import asyncio
import importlib
import json

import database
from models.node import Node
from models.user import User
from models.work import CanvasWork

ct = importlib.import_module("services.agents.tools.chapter_tools")
wc = importlib.import_module("services.chapter_word_count")


def _make_work(db, title="w"):
    user = User(username=f"u-{title}", email=f"{title}@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title=title)
    db.add(work)
    db.commit()
    return work


def test_chapter_body_word_count_strips_whitespace():
    assert wc.chapter_body_word_count("林川 进入\n档案室") == len("林川进入档案室")


def test_build_word_count_advice():
    assert "篇幅合适" in wc.build_word_count_advice(3000, 3000)
    assert "少" in wc.build_word_count_advice(2000, 3000)
    assert "多" in wc.build_word_count_advice(4000, 3000)


def test_count_chapter_words_returns_word_count():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(sort_order=0, 
            work_id=work.id,
            type="chapter",
            title="第一章",
            content="这是一段测试文字，共有若干个字。",
        )
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(ct._count_chapter_words_coroutine(node.id, work_id=work.id)))

        assert result["success"] is True
        assert result["word_count"] == wc.chapter_body_word_count(node.content)
        assert result["chapter"]["title"] == "第一章"
    finally:
        db.close()


def test_count_chapter_words_with_expected_advice():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(sort_order=0, work_id=work.id, type="chapter", title="第一章", content="abcde")
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(
            ct._count_chapter_words_coroutine(node.id, expected_word_count=3000, work_id=work.id),
        ))

        assert result["success"] is True
        assert result["word_count"] == 5
        assert "advice" in result
        assert "少" in result["advice"]
    finally:
        db.close()


def test_count_chapter_words_rejects_invalid_expected():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(sort_order=0, work_id=work.id, type="chapter", title="第一章", content="正文")
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(
            ct._count_chapter_words_coroutine(node.id, expected_word_count=0, work_id=work.id),
        ))
        assert "error" in result
    finally:
        db.close()


def test_count_chapter_words_picks_latest_when_node_id_omitted():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        old = Node(
            work_id=work.id, type="chapter", title="第一章",
            content="旧章", sort_order=1,
        )
        latest = Node(
            work_id=work.id, type="chapter", title="第二章",
            content="最新章节正文", sort_order=2,
        )
        db.add_all([old, latest])
        db.commit()

        result = json.loads(asyncio.run(
            ct._count_chapter_words_coroutine(None, work_id=work.id),
        ))

        assert result["success"] is True
        assert result["chapter"]["id"] == latest.id
        assert result["word_count"] == wc.chapter_body_word_count("最新章节正文")
    finally:
        db.close()


def test_count_chapter_words_tool_registered():
    names = {t.name for t in ct.chapter_tools}
    assert "count_chapter_words" in names
