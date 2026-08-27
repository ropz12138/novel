"""连线端点类型限制测试 — TDD。

- worldbuilding/note（全局节点）禁止任何连线
- element 不再是画布节点类型，legacy element 不允许再创建新连线
"""
import importlib
import json

from node_types import validate_edge_endpoints
import database
from models.user import User
from models.work import CanvasWork
from models.node import Node

nt = importlib.import_module("services.agents.tools.node_tools")


# ---------- validate_edge_endpoints 纯函数 ----------

def test_global_scope_cannot_be_edge_endpoint():
    # scope=global 禁线（worldbuilding/note + 主角 character）
    assert validate_edge_endpoints("worldbuilding", "chapter", "global", "local")
    assert validate_edge_endpoints("chapter", "note", "local", "global")
    assert validate_edge_endpoints("character", "chapter", "global", "minor")  # 主角 global 禁


def test_non_global_character_allowed():
    # character 非全局（major/minor/temp）允许连线
    assert validate_edge_endpoints("character", "chapter", "minor", "local") is None
    assert validate_edge_endpoints("chapter", "character", "local", "major") is None


def test_element_is_no_longer_allowed_as_edge_endpoint():
    assert validate_edge_endpoints("element", "volume", "local", "local")     # 非chapter 拒绝
    assert validate_edge_endpoints("element", "chapter", "local", "local")
    assert validate_edge_endpoints("chapter", "element", "local", "local")    # element 作 target 拒绝
    assert validate_edge_endpoints("outline", "element", "local", "local")


def test_normal_edges_allowed():
    assert validate_edge_endpoints("outline", "volume", "local", "local") is None
    assert validate_edge_endpoints("volume", "plot", "local", "local") is None
    assert validate_edge_endpoints("chapter", "character", "local", "minor") is None


def test_character_to_character_edge_forbidden():
    err = validate_edge_endpoints("character", "character", "minor", "major")
    assert err is not None
    assert "character_relations" in err


# ---------- create_edge 工具集成 ----------

def _make_work(monkeypatch, db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def test_create_edge_rejects_global_node(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        wb = Node(work_id=work.id, type="worldbuilding", title="世界观", scope="global")
        ch = Node(work_id=work.id, type="chapter", title="章节")
        db.add_all([wb, ch])
        db.commit()
        r = json.loads(nt._create_edge_sync(wb.id, ch.id, edge_type="关联"))
        assert "error" in r
    finally:
        db.close()


def test_create_edge_rejects_element_to_non_chapter(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        elem = Node(work_id=work.id, type="element", title="觉醒")
        vol = Node(work_id=work.id, type="volume", title="卷")
        db.add_all([elem, vol])
        db.commit()
        r = json.loads(nt._create_edge_sync(elem.id, vol.id, edge_type="包含"))
        assert "error" in r
    finally:
        db.close()


def test_create_edge_rejects_element_as_target(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        ch = Node(work_id=work.id, type="chapter", title="章节")
        elem = Node(work_id=work.id, type="element", title="觉醒")
        db.add_all([ch, elem])
        db.commit()
        r = json.loads(nt._create_edge_sync(ch.id, elem.id, edge_type="包含"))
        assert "error" in r
    finally:
        db.close()


def test_create_edge_rejects_element_to_chapter(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        elem = Node(work_id=work.id, type="element", title="觉醒")
        ch = Node(work_id=work.id, type="chapter", title="章节")
        db.add_all([elem, ch])
        db.commit()
        r = json.loads(nt._create_edge_sync(elem.id, ch.id, edge_type="包含"))
        assert "error" in r
    finally:
        db.close()


def test_create_edge_rejects_protagonist_character(monkeypatch):
    # 主角（character scope=global）也属全局节点，禁连线
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        protagonist = Node(work_id=work.id, type="character", title="主角", scope="global")
        ch = Node(work_id=work.id, type="chapter", title="章节")
        db.add_all([protagonist, ch])
        db.commit()
        r = json.loads(nt._create_edge_sync(protagonist.id, ch.id, edge_type="登场"))
        assert "error" in r
    finally:
        db.close()
