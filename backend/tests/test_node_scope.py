"""Node.scope 字段测试 — character 角色分类版。

scope 取 5 值：global / local / major / minor / temp
- worldbuilding/style：固定 global（全局节点）
- outline/volume/plot/chapter：固定 local（层级链）
- character：global(主角) / major(主要配角) / minor(次要配角,默认) / temp(临时)，
  不允许 local（局部未细分已废弃）
"""
import importlib
import json

import pytest

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node

node_types = importlib.import_module("node_types")
nt = importlib.import_module("services.agents.tools.node_tools")


def _make_work(monkeypatch, db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


# ---------- scope 枚举与校验 ----------

def test_standard_scopes_has_five_values():
    assert set(node_types.STANDARD_SCOPES) == {"global", "local", "major", "minor", "temp"}


def test_validate_scope_accepts_all_five():
    for s in ("global", "local", "major", "minor", "temp"):
        assert node_types.validate_scope(s) == s


def test_validate_scope_rejects_unknown():
    for bad in ("", "universal", "work", None):
        with pytest.raises(ValueError):
            node_types.validate_scope(bad)


# ---------- 类型默认 scope ----------

def test_default_scope_for_type():
    assert node_types.default_scope_for_type("worldbuilding") == "global"
    assert node_types.default_scope_for_type("style") == "global"
    for t in ("outline", "volume", "plot", "chapter"):
        assert node_types.default_scope_for_type(t) == "local"
    # character 默认 minor（次要配角）
    assert node_types.default_scope_for_type("character") == "minor"


def test_global_locked_types_only_worldbuilding_and_style():
    assert set(node_types.GLOBAL_LOCKED_TYPES) == {"worldbuilding", "style"}


def test_local_locked_types_are_hierarchy_chain():
    assert set(node_types.LOCAL_LOCKED_TYPES) == {"outline", "volume", "plot", "chapter"}


def test_character_scopes_exclude_local():
    assert node_types.CHARACTER_SCOPES == frozenset({"global", "major", "minor", "temp"})
    assert "local" not in node_types.CHARACTER_SCOPES


# ---------- resolve_scope：创建时统一解析 ----------

def test_resolve_scope_locked_global_forces_global_when_omitted():
    assert node_types.resolve_scope("worldbuilding", None) == "global"
    assert node_types.resolve_scope("style", None) == "global"


def test_resolve_scope_locked_global_rejects_local():
    with pytest.raises(ValueError):
        node_types.resolve_scope("worldbuilding", "local")


def test_resolve_scope_hierarchy_forces_local():
    for t in ("outline", "volume", "plot", "chapter"):
        assert node_types.resolve_scope(t, None) == "local"


def test_resolve_scope_hierarchy_rejects_global():
    with pytest.raises(ValueError):
        node_types.resolve_scope("chapter", "global")


def test_resolve_scope_character_defaults_minor():
    assert node_types.resolve_scope("character", None) == "minor"


def test_resolve_scope_character_accepts_four_roles():
    for s in ("global", "major", "minor", "temp"):
        assert node_types.resolve_scope("character", s) == s


def test_resolve_scope_character_rejects_local():
    with pytest.raises(ValueError):
        node_types.resolve_scope("character", "local")


# ---------- Model 字段 ----------

def test_node_scope_default_local_at_orm_level():
    # ORM 层 default 仍是 'local'（层级链节点）；character 的 minor 由工具层 resolve 注入
    db = database.SessionLocal()
    try:
        user = User(username="u", email="u@u.u", password_hash="x")
        db.add(user)
        db.commit()
        work = CanvasWork(user_id=user.id, title="w")
        db.add(work)
        db.commit()
        node = Node(work_id=work.id, type="outline", title="主线")
        db.add(node)
        db.commit()
        db.refresh(node)
        assert node.scope == "local"
    finally:
        db.close()


# ---------- create_node 工具 ----------

def test_create_node_defaults_scope_by_type(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        # outline 默认 local
        r = json.loads(nt._create_node_sync("outline", "主线", layer=1))
        assert r["success"] is True
        assert r["node"]["scope"] == "local"

        # worldbuilding 默认 global
        r2 = json.loads(nt._create_node_sync("worldbuilding", "世界观", layer=0))
        assert r2["success"] is True
        assert r2["node"]["scope"] == "global"

        # character 默认 minor
        r3 = json.loads(nt._create_node_sync("character", "配角A", layer=0))
        assert r3["success"] is True
        assert r3["node"]["scope"] == "minor"
    finally:
        db.close()


def test_create_node_accepts_global_for_protagonist(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        r = json.loads(
            nt._create_node_sync("character", "主角", scope="global", layer=0)
        )
        assert r["success"] is True
        assert r["node"]["scope"] == "global"
    finally:
        db.close()


def test_create_node_character_rejects_local(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        r = json.loads(
            nt._create_node_sync("character", "X", scope="local", layer=0)
        )
        assert "error" in r
    finally:
        db.close()


def test_create_node_rejects_invalid_scope(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        r = json.loads(
            nt._create_node_sync("character", "X", scope="universal", layer=0)
        )
        assert "error" in r
    finally:
        db.close()


# ---------- update_node 工具 ----------

def test_update_node_changes_scope_minor_to_global(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        c = Node(work_id=work.id, type="character", title="主角", scope="minor", layer=0)
        db.add(c)
        db.commit()

        r = json.loads(nt._update_node_sync(c.id, scope="global"))
        assert r["success"] is True
        assert r["node"]["scope"] == "global"
    finally:
        db.close()


def test_update_node_character_rejects_local(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        c = Node(work_id=work.id, type="character", title="X", scope="minor", layer=0)
        db.add(c)
        db.commit()

        r = json.loads(nt._update_node_sync(c.id, scope="local"))
        assert "error" in r
    finally:
        db.close()


def test_update_node_keeps_scope_when_untouched(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        c = Node(work_id=work.id, type="character", title="主角",
                 scope="global", layer=0)
        db.add(c)
        db.commit()

        r = json.loads(nt._update_node_sync(c.id, title="主角改名"))
        assert r["success"] is True
        assert r["node"]["scope"] == "global"
    finally:
        db.close()


def test_update_node_resets_scope_when_type_changes_to_locked(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        c = Node(work_id=work.id, type="character", title="X",
                 scope="minor", layer=0)
        db.add(c)
        db.commit()

        r = json.loads(nt._update_node_sync(c.id, node_type="worldbuilding"))
        assert r["success"] is True
        assert r["node"]["scope"] == "global"
    finally:
        db.close()


# ---------- _compact 带 scope ----------

def test_compact_includes_scope():
    db = database.SessionLocal()
    try:
        user = User(username="c", email="c@c.c", password_hash="x")
        db.add(user)
        db.commit()
        work = CanvasWork(user_id=user.id, title="cw")
        db.add(work)
        db.commit()
        node = Node(work_id=work.id, type="character", title="主角",
                    scope="global", layer=0)
        db.add(node)
        db.commit()
        db.refresh(node)

        compact = nt._compact(node)
        assert compact["scope"] == "global"
        assert set(compact.keys()) == {"id", "type", "title", "layer", "scope", "locked"}
    finally:
        db.close()


# ---------- batch_create_nodes 支持 scope ----------

def test_batch_create_nodes_resolves_scope_per_node(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        r = json.loads(nt._batch_create_nodes_sync(nodes_data=[
            {"node_type": "character", "title": "主角", "scope": "global", "layer": 0},
            {"node_type": "character", "title": "配角", "layer": 0},  # 默认 minor
            {"node_type": "worldbuilding", "title": "世界观", "layer": 0},
        ]))
        assert r["success"] is True
        scopes = [n["scope"] for n in r["nodes"]]
        assert scopes == ["global", "minor", "global"]
    finally:
        db.close()
