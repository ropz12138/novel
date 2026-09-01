"""全局节点上下文注入测试 — TDD。

note/theme/worldbuilding 类型的节点自动作为全局设定，
注入到 Supervisor system prompt 和工具内 LLM 交互中。
"""
import importlib

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node

gc = importlib.import_module("services.global_context")
sup_mod = importlib.import_module("services.agents.supervisor")


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
        note = Node(sort_order=0, work_id=work.id, type="note", title="暗黑风格", content="使用阴暗笔调")
        theme = Node(sort_order=0, work_id=work.id, type="theme", title="救赎", content="主角寻求救赎")
        world = Node(sort_order=0, work_id=work.id, type="worldbuilding", title="魔法体系", content="魔力来源")
        chapter = Node(sort_order=0, work_id=work.id, type="chapter", title="第1章", content="正文")
        db.add_all([note, theme, world, chapter])
        db.commit()

        nodes = gc.get_global_nodes(db, work.id)
        types = {n.type for n in nodes}
        assert types == {"note", "theme", "worldbuilding"}
        assert len(nodes) == 3
    finally:
        db.close()


def test_get_global_nodes_empty_when_no_global_types():
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        ch = Node(sort_order=0, work_id=work.id, type="chapter", title="第1章", content="正文")
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
        note = Node(sort_order=0, work_id=work.id, type="note", title="暗黑风格", content="使用阴暗笔调")
        theme = Node(sort_order=0, work_id=work.id, type="theme", title="救赎", content="主角寻求救赎")
        db.add_all([note, theme])
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
        note = Node(sort_order=0, work_id=work.id, type="note", title="硬汉派", content="简洁有力的对白")
        world = Node(sort_order=0, work_id=work.id, type="worldbuilding", title="赛博朋克", content="高科技低生活")
        db.add_all([note, world])
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
