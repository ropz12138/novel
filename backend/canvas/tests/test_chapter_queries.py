"""章节邻域与前序章节查询测试。"""
import json
import importlib

from app import database
from app.models.chapter import Chapter
from app.models.edge import Edge
from app.models.node import Node
from app.models.user import User
from app.models.work import CanvasWork

qt = importlib.import_module("app.services.agents.tools.query_tools")


def _make_work(db, title="work"):
    user = User(username=f"u-{title}", email=f"{title}@test.local", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title=title)
    db.add(work)
    db.commit()
    return work


def test_chapter_neighborhood_returns_complete_relationships(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        chapter = Node(work_id=work.id, type="chapter", title="第2章", content="")
        character = Node(work_id=work.id, type="character", title="林川", content="谨慎的调查员")
        event = Node(work_id=work.id, type="event", title="公开冲突", content="反派质疑林川资格")
        db.add_all([chapter, character, event])
        db.commit()
        db.add_all([
            Edge(
                work_id=work.id,
                source_id=chapter.id,
                target_id=character.id,
                edge_type="本章迫使他公开选择阵营",
                label="章末立场发生变化",
            ),
            Edge(
                work_id=work.id,
                source_id=event.id,
                target_id=chapter.id,
                edge_type="本章具体实施",
                label="通过公开质疑引出矛盾",
            ),
        ])
        db.commit()
        monkeypatch.setattr(qt, "_get_current_work_id", lambda: work.id)

        result = json.loads(qt._get_chapter_neighborhood_sync(chapter.id))

        assert result["chapter"]["id"] == chapter.id
        assert {node["id"] for node in result["nodes"]} == {
            chapter.id, character.id, event.id,
        }
        relation = next(edge for edge in result["edges"] if edge["target_id"] == character.id)
        assert relation["direction"] == "out"
        assert relation["source_type"] == "chapter"
        assert relation["target_type"] == "character"
        assert relation["label"] == "章末立场发生变化"
        assert any("通过公开质疑引出矛盾" in line for line in result["planning_summary"])
    finally:
        db.close()


def test_read_node_content_is_scoped_to_work(monkeypatch):
    db = database.SessionLocal()
    try:
        work1 = _make_work(db, "one")
        work2 = _make_work(db, "two")
        foreign = Node(work_id=work2.id, type="idea", title="其他作品", content="secret")
        db.add(foreign)
        db.commit()
        monkeypatch.setattr(qt, "_get_current_work_id", lambda: work1.id)

        result = json.loads(qt._read_node_content_sync([foreign.id]))

        assert result["error"] == "未找到节点"
    finally:
        db.close()


def test_previous_chapters_uses_explicit_order_and_returns_summary(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        ch1 = Node(
            work_id=work.id, type="chapter", title="第一章",
            content="事实一", extra_data={"chapter_order": 1}, position_x=900,
        )
        ch2 = Node(
            work_id=work.id, type="chapter", title="第二章",
            content="事实二", extra_data={"chapter_order": 2}, position_x=100,
        )
        ch3 = Node(
            work_id=work.id, type="chapter", title="第三章",
            content="", extra_data={"chapter_order": 3}, position_x=0,
        )
        db.add_all([ch1, ch2, ch3])
        db.commit()
        db.add(Chapter(work_id=work.id, node_id=ch2.id, summary="第二章摘要"))
        db.commit()
        monkeypatch.setattr(qt, "_get_current_work_id", lambda: work.id)

        result = json.loads(qt._get_previous_chapters_sync(ch3.id, limit=2))

        assert [chapter["title"] for chapter in result["chapters"]] == ["第一章", "第二章"]
        assert result["chapters"][1]["summary"] == "第二章摘要"
        assert result["chapters"][0]["content"] == "事实一"
    finally:
        db.close()


def test_chapter_query_tools_registered():
    names = {tool.name for tool in qt.query_tools}
    assert {"get_chapter_neighborhood", "get_previous_chapters"} <= names
