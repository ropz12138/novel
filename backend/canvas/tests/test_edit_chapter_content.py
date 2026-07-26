"""edit_chapter_content 工具测试 — TDD。"""
import asyncio
import importlib
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app import database
from app.models.chapter import Chapter
from app.models.node import Node
from app.models.user import User
from app.models.work import CanvasWork

ct = importlib.import_module("app.services.agents.tools.chapter_tools")
llm_mod = importlib.import_module("app.services.agents.llm")
supervisor_mod = importlib.import_module("app.services.agents.supervisor")


class FakeLLM:
    def __init__(self, captured, response):
        self.captured = captured
        self.response = response

    async def ainvoke(self, messages, config=None, **kwargs):
        self.captured["messages"] = messages
        return self.response

    async def astream(self, messages, config=None, **kwargs):
        self.captured["messages"] = messages
        yield self.response


def _make_work(db):
    user = User(username="edit-t", email="edit-t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    return work


def _edits_response(edits):
    return AIMessage(content=json.dumps({"edits": edits}, ensure_ascii=False))


def test_edit_chapter_content_applies_and_returns_diff(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM(captured, _edits_response([{
            "type": "replace",
            "paragraph_index": 1,
            "old_text": "旧段落",
            "new_text": "新段落",
        }])),
    )
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(work_id=work.id, type="chapter", title="第1章", content="旧段落")
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(
            ct._edit_chapter_content_coroutine(node.id, "把段落改一下", "上下文")
        ))
        assert result["success"] is True
        assert result["diff"]["hunks"][0]["new_text"] == "新段落"
        db.refresh(node)
        assert node.content == "新段落"
    finally:
        db.close()


def test_edit_chapter_content_validation_failure_returns_fallback_hint(monkeypatch):
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM({}, _edits_response([{
            "type": "replace",
            "paragraph_index": 1,
            "old_text": "不存在",
            "new_text": "新",
        }])),
    )
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(work_id=work.id, type="chapter", title="第1章", content="旧段落")
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(
            ct._edit_chapter_content_coroutine(node.id, "改", "")
        ))
        assert result["success"] is False
        assert result["fallback_hint"] == "write_chapter"
        db.refresh(node)
        assert node.content == "旧段落"
    finally:
        db.close()


def test_edit_chapter_content_clears_summary(monkeypatch, db_session):
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM({}, _edits_response([{
            "type": "replace",
            "paragraph_index": 1,
            "old_text": "旧",
            "new_text": "新",
        }])),
    )
    work = _make_work(db_session)
    node = Node(work_id=work.id, type="chapter", title="第1章", content="旧")
    db_session.add(node)
    db_session.commit()
    row = Chapter(work_id=work.id, node_id=node.id, title=node.title, summary="旧摘要")
    db_session.add(row)
    db_session.commit()

    result = json.loads(asyncio.run(
        ct._edit_chapter_content_coroutine(node.id, "改", "")
    ))
    assert result["success"] is True
    db_session.refresh(row)
    assert row.summary == ""


def test_edit_chapter_content_emits_chapter_edit_diff(monkeypatch):
    events = []

    async def collect(event, data):
        events.append((event, data))

    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM({}, _edits_response([{
            "type": "replace",
            "paragraph_index": 1,
            "old_text": "旧",
            "new_text": "新",
        }])),
    )
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(work_id=work.id, type="chapter", title="第1章", content="旧")
        db.add(node)
        db.commit()
        supervisor_mod.set_context({"work_id": work.id, "emit": collect})

        asyncio.run(ct._edit_chapter_content_coroutine(node.id, "改", ""))

        event_names = [e[0] for e in events]
        assert "chapter_edit_diff" in event_names
        assert "nodes_updated" in event_names
        diff_event = next(d for e, d in events if e == "chapter_edit_diff")
        assert diff_event["chapter_node_id"] == node.id
    finally:
        supervisor_mod.set_context({})
        db.close()


def test_edit_chapter_prompt_includes_full_content(monkeypatch):
    captured = {}
    long_body = "段落一。\n\n段落二。"
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM(captured, _edits_response([])),
    )
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(work_id=work.id, type="chapter", title="第1章", content=long_body)
        db.add(node)
        db.commit()

        asyncio.run(ct._edit_chapter_content_coroutine(node.id, "改第二段", "角色设定"))

        human = captured["messages"][1]
        assert isinstance(human, HumanMessage)
        assert "段落一。" in human.content
        assert "段落二。" in human.content
        assert "改第二段" in human.content
        assert "角色设定" in human.content
    finally:
        db.close()


def test_supervisor_mounts_edit_chapter_content():
    from app.services.agents.supervisor import SupervisorAgent

    tools = SupervisorAgent()._get_tools()
    names = [t.name for t in tools]
    assert "edit_chapter_content" not in names
