"""write_chapter 章节情节元素(element)注入测试 — TDD。

element = 比 plot 更细的具体情节单元（觉醒/吵架等），挂章节下(chapter contains element)、可跨章复用。
write_chapter 工具内部查本章关联的 element，注入提示词，让正文涵盖这些情节单元。
"""
import importlib

from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node
from app.models.edge import Edge

ct = importlib.import_module("app.services.agents.tools.chapter_tools")


# ---------- _build_write_chapter_messages：element 段注入 ----------

def test_build_messages_includes_elements_section():
    msgs = ct._build_write_chapter_messages(
        user_directive="写第一章",
        context="【大纲】...",
        extra="",
        elements=[{"title": "主角觉醒", "content": "林远在危机中觉醒时间感知"}, {"title": "与张猛相遇", "content": "图书馆逃亡遇到张猛"}],
    )
    human = msgs[1].content
    assert "本章情节元素" in human
    assert "主角觉醒" in human
    assert "与张猛相遇" in human


def test_build_messages_omits_elements_section_when_empty():
    msgs = ct._build_write_chapter_messages(
        user_directive="写第一章",
        context="【大纲】...",
        extra="",
        elements=None,
    )
    human = msgs[1].content
    assert "本章情节元素" not in human


# ---------- _collect_chapter_elements：查 contains 出边的 element ----------

def _make_work(db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    return work


def test_collect_chapter_elements_returns_linked_elements():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        ch = Node(work_id=work.id, type="chapter", title="第一章", content="")
        e1 = Node(work_id=work.id, type="element", title="主角觉醒", content="林远觉醒时间感知")
        e2 = Node(work_id=work.id, type="element", title="与张猛相遇", content="图书馆遇到张猛")
        db.add_all([ch, e1, e2])
        db.commit()
        db.add(Edge(work_id=work.id, source_id=e1.id, target_id=ch.id, edge_type="contains"))
        db.add(Edge(work_id=work.id, source_id=e2.id, target_id=ch.id, edge_type="包含"))
        db.commit()

        elements = ct._collect_chapter_elements(db, ch.id, work.id)
        titles = {e["title"] for e in elements}
        assert titles == {"主角觉醒", "与张猛相遇"}
        contents = {e["content"] for e in elements}
        assert "林远觉醒时间感知" in contents
    finally:
        db.close()


def test_collect_chapter_elements_ignores_non_element_targets():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        ch = Node(work_id=work.id, type="chapter", title="第一章", content="")
        # contains 指向非 element（如 plot）→ 不算元素
        plot = Node(work_id=work.id, type="plot", title="情节", content="xxx")
        db.add_all([ch, plot])
        db.commit()
        # element→chapter 方向；plot→chapter（plot 非 element）不算元素
        db.add(Edge(work_id=work.id, source_id=plot.id, target_id=ch.id, edge_type="contains"))
        db.commit()

        assert ct._collect_chapter_elements(db, ch.id, work.id) == []
    finally:
        db.close()


def test_collect_chapter_elements_empty_when_no_contains():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        ch = Node(work_id=work.id, type="chapter", title="第一章", content="")
        db.add(ch)
        db.commit()
        assert ct._collect_chapter_elements(db, ch.id, work.id) == []
    finally:
        db.close()


def test_element_can_be_shared_across_chapters():
    # element 跨章复用：同一 element 被两个 chapter contains
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        ch1 = Node(work_id=work.id, type="chapter", title="第一章")
        ch2 = Node(work_id=work.id, type="chapter", title="第二章")
        elem = Node(work_id=work.id, type="element", title="神秘晶核", content="蓝色晶核")
        db.add_all([ch1, ch2, elem])
        db.commit()
        db.add(Edge(work_id=work.id, source_id=elem.id, target_id=ch1.id, edge_type="contains"))
        db.add(Edge(work_id=work.id, source_id=elem.id, target_id=ch2.id, edge_type="contains"))
        db.commit()

        e1 = ct._collect_chapter_elements(db, ch1.id, work.id)
        e2 = ct._collect_chapter_elements(db, ch2.id, work.id)
        assert {e["title"] for e in e1} == {"神秘晶核"}
        assert {e["title"] for e in e2} == {"神秘晶核"}
    finally:
        db.close()
