"""insert_chapter_illustration 工具测试 — TDD。"""
import asyncio
import importlib
import json
from pathlib import Path

import pytest

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node
from models.chapter_illustration import ChapterIllustration

it = importlib.import_module("services.agents.tools.illustration_tools")
svc = importlib.import_module("services.chapter_illustration_service")


def _make_work(db):
    user = User(username="illus", email="illus@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="插画测试")
    db.add(work)
    db.commit()
    return work


def _fake_generate(api_key, prompt, save_path, size):
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake-png")


def test_insert_chapter_illustration_persists_and_updates_content(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "ILLUSTRATIONS_DIR", tmp_path)
    monkeypatch.setattr(svc, "generate_and_save", _fake_generate)
    monkeypatch.setattr(it, "_get_current_work_id", lambda: None)

    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(sort_order=0, 
            work_id=work.id,
            type="chapter",
            title="第1章",
            content="开篇段落。\n\n转折段落。",
            layer=3,
        )
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(it._insert_chapter_illustration_coroutine(
            chapter_node_id=node.id,
            prompt="古风庭院夜景，月光洒落，安静悬疑",
            insert_after_paragraph=1,
            work_id=work.id,
        )))
        assert result["success"] is True
        assert result["insert_after_paragraph"] == 1
        assert "illustration_id" in result

        db.refresh(node)
        assert "/api/illustrations/" in node.content
        assert node.content.index("开篇段落。") < node.content.index("![章节插画]")
        assert node.content.index("![章节插画]") < node.content.index("转折段落。")

        row = db.query(ChapterIllustration).filter(
            ChapterIllustration.id == result["illustration_id"]
        ).one()
        assert row.prompt == "古风庭院夜景，月光洒落，安静悬疑"
        assert Path(row.file_path).exists()
    finally:
        db.close()


def test_insert_chapter_illustration_rejects_non_chapter(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "ILLUSTRATIONS_DIR", tmp_path)
    monkeypatch.setattr(svc, "generate_and_save", _fake_generate)

    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(sort_order=0, work_id=work.id, type="plot", title="情节", content="x", layer=2)
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(it._insert_chapter_illustration_coroutine(
            chapter_node_id=node.id,
            prompt="test",
            insert_after_paragraph=1,
            work_id=work.id,
        )))
        assert "error" in result
        assert "chapter" in result["error"].lower() or "章节" in result["error"]
    finally:
        db.close()


def test_insert_chapter_illustration_rejects_empty_content(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "ILLUSTRATIONS_DIR", tmp_path)
    monkeypatch.setattr(svc, "generate_and_save", _fake_generate)

    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(sort_order=0, work_id=work.id, type="chapter", title="空章", content="", layer=3)
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(it._insert_chapter_illustration_coroutine(
            chapter_node_id=node.id,
            prompt="test",
            insert_after_paragraph=1,
            work_id=work.id,
        )))
        assert "error" in result
    finally:
        db.close()


def test_insert_chapter_illustration_rejects_position_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "ILLUSTRATIONS_DIR", tmp_path)
    monkeypatch.setattr(svc, "generate_and_save", _fake_generate)

    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(sort_order=0, 
            work_id=work.id,
            type="chapter",
            title="第1章",
            content="已有剧情段落。",
            layer=3,
        )
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(it._insert_chapter_illustration_coroutine(
            chapter_node_id=node.id,
            prompt="test",
            insert_after_paragraph=0,
            work_id=work.id,
        )))
        assert "error" in result
        assert "正文最前" in result["error"]
    finally:
        db.close()


def test_insert_chapter_illustration_rejects_english_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(svc, "ILLUSTRATIONS_DIR", tmp_path)
    monkeypatch.setattr(svc, "generate_and_save", _fake_generate)

    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(sort_order=0, 
            work_id=work.id,
            type="chapter",
            title="第1章",
            content="已有剧情段落。",
            layer=3,
        )
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(it._insert_chapter_illustration_coroutine(
            chapter_node_id=node.id,
            prompt="A zombie in a school corridor",
            insert_after_paragraph=1,
            work_id=work.id,
        )))
        assert "error" in result
        assert "中文" in result["error"]
    finally:
        db.close()


def test_insert_chapter_illustration_tool_registered():
    names = {t.name for t in it.illustration_tools}
    assert "insert_chapter_illustration" in names
