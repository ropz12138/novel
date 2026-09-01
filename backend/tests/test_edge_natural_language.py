"""Edge 关系纯自然语言测试 — TDD：去掉 RESERVED_EDGE_TYPES。

contains/inherits 不再是布局保留类型，降级为普通自然语言关系。
保留的校验仅为数据完整性：非空、长度≤100。
"""
import importlib
import json

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node

nt = importlib.import_module("services.agents.tools.node_tools")


def _make_work(db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="测试作品")
    db.add(work)
    db.commit()
    return work


def _patch_work(monkeypatch, work_id):
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work_id)


def test_reserved_edge_types_constant_gone():
    assert not getattr(nt, "RESERVED_EDGE_TYPES", set())


def test_contains_is_plain_natural_language(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        _patch_work(monkeypatch, work.id)
        n1 = Node(sort_order=0, work_id=work.id, type="outline", title="主线", layer=1)
        n2 = Node(sort_order=0, work_id=work.id, type="volume", title="第一卷", layer=2)
        db.add_all([n1, n2])
        db.commit()

        result = json.loads(nt._create_edge_sync(n1.id, n2.id, edge_type="包含"))
        assert result["success"] is True
        assert result["edge"]["edge_type"] == "包含"
    finally:
        db.close()


def test_arbitrary_natural_language_edge(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        _patch_work(monkeypatch, work.id)
        n1 = Node(sort_order=0, work_id=work.id, type="character", title="主角", layer=2)
        n2 = Node(sort_order=0, work_id=work.id, type="chapter", title="第1章", layer=3)
        db.add_all([n1, n2])
        db.commit()

        result = json.loads(nt._create_edge_sync(n1.id, n2.id, edge_type="角色登场"))
        assert result["success"] is True
        assert result["edge"]["edge_type"] == "角色登场"
    finally:
        db.close()


def test_empty_edge_type_rejected(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(db)
        _patch_work(monkeypatch, work.id)
        n1 = Node(sort_order=0, work_id=work.id, type="idea", title="a")
        n2 = Node(sort_order=0, work_id=work.id, type="idea", title="b")
        db.add_all([n1, n2])
        db.commit()

        result = json.loads(nt._create_edge_sync(n1.id, n2.id, edge_type="   "))
        assert "error" in result
    finally:
        db.close()
