"""全局节点上下文注入测试 — TDD。

style/theme/worldbuilding 类型的节点自动作为全局设定，
注入到 Supervisor system prompt 和工具内 LLM 交互中。
"""
import asyncio
import importlib
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node

gc = importlib.import_module("app.services.global_context")
ct = importlib.import_module("app.services.agents.tools.chapter_tools")
llm_mod = importlib.import_module("app.services.agents.llm")
sup_mod = importlib.import_module("app.services.agents.supervisor")


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


# ── get_global_nodes 测试 ──


def test_get_global_nodes_returns_only_global_types():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        style = Node(work_id=work.id, type="style", title="暗黑风格", content="使用阴暗笔调")
        theme = Node(work_id=work.id, type="theme", title="救赎", content="主角寻求救赎")
        world = Node(work_id=work.id, type="worldbuilding", title="魔法体系", content="魔力来源")
        chapter = Node(work_id=work.id, type="chapter", title="第1章", content="正文")
        db.add_all([style, theme, world, chapter])
        db.commit()

        nodes = gc.get_global_nodes(db, work.id)
        types = {n.type for n in nodes}
        assert types == {"style", "theme", "worldbuilding"}
        assert len(nodes) == 3
    finally:
        db.close()


def test_get_global_nodes_empty_when_no_global_types():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        ch = Node(work_id=work.id, type="chapter", title="第1章", content="正文")
        db.add(ch)
        db.commit()

        nodes = gc.get_global_nodes(db, work.id)
        assert nodes == []
    finally:
        db.close()


# ── format_global_context 测试 ──


def test_format_global_context_with_nodes():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        style = Node(work_id=work.id, type="style", title="暗黑风格", content="使用阴暗笔调")
        theme = Node(work_id=work.id, type="theme", title="救赎", content="主角寻求救赎")
        db.add_all([style, theme])
        db.commit()

        nodes = gc.get_global_nodes(db, work.id)
        text = gc.format_global_context(nodes)
        assert "全局设定" in text
        assert "暗黑风格" in text
        assert "使用阴暗笔调" in text
        assert "救赎" in text
        assert "主角寻求救赎" in text
    finally:
        db.close()


def test_format_global_context_empty_returns_empty():
    assert gc.format_global_context([]) == ""


# ── Supervisor system prompt 注入测试 ──


def test_supervisor_prompt_excludes_global_context():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        style = Node(work_id=work.id, type="style", title="硬汉派", content="简洁有力的对白")
        world = Node(work_id=work.id, type="worldbuilding", title="赛博朋克", content="高科技低生活")
        db.add_all([style, world])
        db.commit()

        agent = sup_mod.SupervisorAgent()
        prompt = agent._build_system_prompt()
        assert "全局设定" not in prompt
        assert "硬汉派" not in prompt
        assert "简洁有力的对白" not in prompt
        assert "赛博朋克" not in prompt
        assert "高科技低生活" not in prompt
    finally:
        db.close()


def test_supervisor_prompt_no_global_section():
    agent = sup_mod.SupervisorAgent()
    prompt = agent._build_system_prompt()
    assert "全局设定" not in prompt


# ── write_chapter LLM 注入测试 ──


def test_write_chapter_includes_global_context_in_system_message(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        llm_mod, "get_llm",
        lambda **kw: FakeLLM(captured, AIMessage(content="正文")),
    )
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        style = Node(work_id=work.id, type="style", title="诗意", content="大量使用比喻")
        db.add(style)
        db.commit()

        ch = Node(work_id=work.id, type="chapter", title="第1章", layer=3)
        db.add(ch)
        db.commit()

        asyncio.run(ct._write_chapter_coroutine(ch.id, "写第一章", "前文", "", work_id=work.id))

        messages = captured["messages"]
        system_msg = messages[0]
        assert isinstance(system_msg, SystemMessage)
        assert "全局设定" in system_msg.content
        assert "诗意" in system_msg.content
        assert "大量使用比喻" in system_msg.content
    finally:
        db.close()


# ── chapter_generator 注入测试 ──


def test_chapter_generator_prompt_includes_global_context(monkeypatch):
    """chapter_generator._build_prompt 应包含全局设定。"""
    from app.services import chapter_generator

    context = {
        "chapter_title": "第1章",
        "chapter_content": "",
        "extra_instructions": "",
        "related_contexts": [],
        "forbidden_reveals": [],
        "global_context": "## 全局设定\n### 【文风】诗意\n大量使用比喻",
    }
    prompt = chapter_generator._build_prompt(context)
    assert "全局设定" in prompt
    assert "诗意" in prompt
