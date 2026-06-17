"""write_chapter 胖工具测试 — TDD。

三层注入（user_directive/context/extra）+ 静态写作规范；禁止查库（context 由 agent 传入）。
内部调 LLM，测试用 FakeLLM mock。
"""
import asyncio
import importlib
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node
from app.models.edge import Edge

ct = importlib.import_module("app.services.agents.tools.chapter_tools")
llm_mod = importlib.import_module("app.services.agents.llm")
nt = importlib.import_module("app.services.agents.tools.node_tools")


class FakeLLM:
    def __init__(self, captured, response):
        self.captured = captured
        self.response = response

    async def ainvoke(self, messages, config=None, **kwargs):
        self.captured["messages"] = messages
        return self.response


def _make_work(db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    return work


def test_write_chapter_persists_content(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM(captured, AIMessage(content="生成的正文")),
    )
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(work_id=work.id, type="chapter", title="第1章", layer=3)
        db.add(node)
        db.commit()

        result = json.loads(asyncio.run(
            ct._write_chapter_coroutine(node.id, "写第一章", "前文：无", "")
        ))
        assert result["success"] is True
        assert result["node"]["title"] == "第1章"
        db.refresh(node)
        assert node.content == "生成的正文"
    finally:
        db.close()


def test_write_chapter_prompt_directive_first_and_marked(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM(captured, AIMessage(content="正文")),
    )
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(work_id=work.id, type="chapter", title="第1章", layer=3)
        db.add(node)
        db.commit()

        asyncio.run(ct._write_chapter_coroutine(
            node.id, "用户原话：主角登场", "上下文：设定X", "补充：节奏快"
        ))

        messages = captured["messages"]
        assert isinstance(messages[0], SystemMessage)
        human = messages[1]
        assert isinstance(human, HumanMessage)
        text = human.content
        # user_directive 置顶（在 context 之前）
        assert text.index("用户原话：主角登场") < text.index("上下文：设定X")
        # 标注禁止改写
        assert "禁止改写" in text or "逐字遵守" in text
    finally:
        db.close()


def test_write_chapter_returns_neighbors(monkeypatch):
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM({}, AIMessage(content="正文")),
    )
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        ch = Node(work_id=work.id, type="chapter", title="第1章", layer=3)
        outline = Node(work_id=work.id, type="outline", title="主线", layer=1)
        db.add_all([ch, outline])
        db.commit()
        db.add(Edge(work_id=work.id, source_id=outline.id, target_id=ch.id, edge_type="包含"))
        db.commit()

        result = json.loads(asyncio.run(
            ct._write_chapter_coroutine(ch.id, "写", "ctx", "")
        ))
        neighbor_ids = [nb["node"]["id"] for nb in result["neighbors"]]
        assert outline.id in neighbor_ids
    finally:
        db.close()


def test_write_chapter_rejects_nonexistent_node(monkeypatch):
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM({}, AIMessage(content="正文")),
    )
    result = json.loads(asyncio.run(
        ct._write_chapter_coroutine("不存在的id", "写", "ctx", "")
    ))
    assert "error" in result


def test_write_chapter_result_contains_content(monkeypatch):
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM({}, AIMessage(content="生成的正文")),
    )
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        node = Node(work_id=work.id, type="chapter", title="第1章", layer=3)
        db.add(node)
        db.commit()
        result = json.loads(asyncio.run(
            ct._write_chapter_coroutine(node.id, "写第一章", "前文", "")
        ))
        # 返回值必须含正文（设计要求"返回章节节点含正文"）
        assert result["node"]["content"] == "生成的正文"
    finally:
        db.close()


def test_write_chapter_tool_registered():
    names = [t.name for t in ct.chapter_tools]
    assert "write_chapter" in names
