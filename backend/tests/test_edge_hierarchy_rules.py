"""层级关系判定与结构校验 — TDD

关系类别由节点类型派生，不存储字段：
  - 两端为层级链类型且 target 层级 = source 层级 + 1  → hierarchy
  - 两端为同一种层级链类型                            → sequence
  - 其余合法组合                                      → reference
  - 两端为层级链类型但跨级或反向                      → 非法，创建时拒绝

结构校验：自环、跨级、单父。
"""
import importlib
import json

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node
from services.edge_relation import (
    RELATION_HIERARCHY,
    RELATION_SEQUENCE,
    RELATION_REFERENCE,
    hierarchy_level,
    derive_relation_kind,
    validate_relation_types,
    validate_hierarchy_structure,
)

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


def _make_node(db, work_id, title="n", node_type="outline"):
    node = Node(work_id=work_id, type=node_type, title=title, layer=0)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


# ---------- 层级序号 ----------

def test_hierarchy_level_of_chain_types():
    assert hierarchy_level("outline") == 0
    assert hierarchy_level("volume") == 1
    assert hierarchy_level("plot") == 2
    assert hierarchy_level("chapter") == 3


def test_hierarchy_level_of_non_chain_types_is_none():
    assert hierarchy_level("character") is None
    assert hierarchy_level("worldbuilding") is None
    assert hierarchy_level("note") is None


# ---------- 关系类别派生：hierarchy ----------

def test_outline_to_volume_is_hierarchy():
    assert derive_relation_kind("outline", "volume") == RELATION_HIERARCHY


def test_volume_to_plot_is_hierarchy():
    assert derive_relation_kind("volume", "plot") == RELATION_HIERARCHY


def test_plot_to_chapter_is_hierarchy():
    assert derive_relation_kind("plot", "chapter") == RELATION_HIERARCHY


# ---------- 关系类别派生：sequence ----------

def test_chapter_to_chapter_is_sequence_not_hierarchy():
    """核心回归：若判据只看"两端都是层级链类型"，前一章会被误判为后一章的父节点，
    导致树深度错乱。同类型之间必须归为 sequence。"""
    kind = derive_relation_kind("chapter", "chapter")
    assert kind == RELATION_SEQUENCE
    assert kind != RELATION_HIERARCHY


def test_volume_to_volume_is_sequence():
    assert derive_relation_kind("volume", "volume") == RELATION_SEQUENCE


def test_plot_to_plot_is_sequence():
    assert derive_relation_kind("plot", "plot") == RELATION_SEQUENCE


# ---------- 关系类别派生：reference ----------

def test_character_to_chapter_is_reference():
    assert derive_relation_kind("character", "chapter") == RELATION_REFERENCE


def test_character_to_plot_is_reference():
    assert derive_relation_kind("character", "plot") == RELATION_REFERENCE


def test_non_chain_pair_is_reference():
    assert derive_relation_kind("worldbuilding", "note") == RELATION_REFERENCE


# ---------- 关系类别派生：非法 ----------

def test_outline_to_chapter_skips_levels_is_illegal():
    assert derive_relation_kind("outline", "chapter") is None


def test_outline_to_plot_skips_levels_is_illegal():
    assert derive_relation_kind("outline", "plot") is None


def test_volume_to_chapter_skips_levels_is_illegal():
    assert derive_relation_kind("volume", "chapter") is None


def test_reverse_hierarchy_is_illegal():
    assert derive_relation_kind("volume", "outline") is None
    assert derive_relation_kind("chapter", "plot") is None
    assert derive_relation_kind("chapter", "outline") is None


def test_validate_relation_types_reports_error_for_skipped_level():
    err = validate_relation_types("outline", "chapter")
    assert err is not None
    assert "outline" in err and "chapter" in err


def test_validate_relation_types_passes_for_legal_pairs():
    assert validate_relation_types("volume", "plot") is None
    assert validate_relation_types("chapter", "chapter") is None
    assert validate_relation_types("character", "chapter") is None


# ---------- edge_type 自然语言不参与判定 ----------

def test_natural_language_edge_type_does_not_create_hierarchy():
    """edge_type 写"包含"但两端类型不构成降级时，仍不是 hierarchy。"""
    assert derive_relation_kind("chapter", "chapter") == RELATION_SEQUENCE
    assert derive_relation_kind("character", "chapter") == RELATION_REFERENCE


def test_hierarchy_holds_regardless_of_edge_type_text():
    """反之，edge_type 是"参与"这类词，只要类型严格降级仍是 hierarchy。"""
    assert derive_relation_kind("volume", "plot") == RELATION_HIERARCHY


# ---------- 结构校验：自环 ----------

def test_self_loop_rejected(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        node = _make_node(db, work.id, "卷一", "volume")
        err = validate_hierarchy_structure(db, work.id, node, node)
        assert err is not None
    finally:
        db.close()


# ---------- 结构校验：单父 ----------

def test_second_hierarchy_parent_rejected(monkeypatch):
    """同一个 plot 不能同时挂在两个 volume 下，否则树布局结果不确定。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        wid = work.id
        vol1 = _make_node(db, wid, "卷一", "volume")
        vol2 = _make_node(db, wid, "卷二", "volume")
        plot = _make_node(db, wid, "情节", "plot")

        assert validate_hierarchy_structure(db, wid, vol1, plot) is None
        json.loads(nt._create_edge_sync(vol1.id, plot.id, edge_type="包含"))

        err = validate_hierarchy_structure(db, wid, vol2, plot)
        assert err is not None
    finally:
        db.close()


def test_same_parent_twice_rejected(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        wid = work.id
        vol = _make_node(db, wid, "卷一", "volume")
        plot = _make_node(db, wid, "情节", "plot")

        json.loads(nt._create_edge_sync(vol.id, plot.id, edge_type="包含"))
        err = validate_hierarchy_structure(db, wid, vol, plot)
        assert err is not None
    finally:
        db.close()


def test_sequence_edge_does_not_occupy_parent_slot(monkeypatch):
    """chapter → chapter 是 sequence，不占用父节点名额；
    章节仍可以挂在 plot 下。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        wid = work.id
        plot = _make_node(db, wid, "情节", "plot")
        ch1 = _make_node(db, wid, "第一章", "chapter")
        ch2 = _make_node(db, wid, "第二章", "chapter")

        json.loads(nt._create_edge_sync(ch1.id, ch2.id, edge_type="接续"))
        assert validate_hierarchy_structure(db, wid, plot, ch2) is None
    finally:
        db.close()


def test_reference_edge_does_not_occupy_parent_slot(monkeypatch):
    """character → chapter 是 reference，不占用父节点名额。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        wid = work.id
        plot = _make_node(db, wid, "情节", "plot")
        ch = _make_node(db, wid, "第一章", "chapter")
        char = _make_node(db, wid, "角色", "character")

        json.loads(nt._create_edge_sync(char.id, ch.id, edge_type="登场"))
        assert validate_hierarchy_structure(db, wid, plot, ch) is None
    finally:
        db.close()


def test_one_parent_many_children_allowed(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        wid = work.id
        vol = _make_node(db, wid, "卷一", "volume")
        p1 = _make_node(db, wid, "情节一", "plot")
        p2 = _make_node(db, wid, "情节二", "plot")

        json.loads(nt._create_edge_sync(vol.id, p1.id, edge_type="包含"))
        assert validate_hierarchy_structure(db, wid, vol, p2) is None
    finally:
        db.close()


# ---------- 结构校验：环 ----------

def test_hierarchy_cannot_form_cycle_by_construction():
    """严格降一级判据下，hierarchy 边的层级序号严格递增，环需要回到起点层级，
    因此不可能构成环。跨级与反向连接均在类型判定阶段被拒绝，
    无需额外的运行时环检测。"""
    for source in ("outline", "volume", "plot", "chapter"):
        for target in ("outline", "volume", "plot", "chapter"):
            kind = derive_relation_kind(source, target)
            if kind == RELATION_HIERARCHY:
                assert hierarchy_level(target) == hierarchy_level(source) + 1


# ---------- Agent 工具层拒绝 ----------

def test_create_edge_tool_rejects_skipped_level(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        wid = work.id
        outline = _make_node(db, wid, "大纲", "outline")
        ch = _make_node(db, wid, "第一章", "chapter")

        result = json.loads(nt._create_edge_sync(outline.id, ch.id, edge_type="包含"))
        assert "error" in result
    finally:
        db.close()


def test_create_edge_tool_rejects_second_parent(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        wid = work.id
        vol1 = _make_node(db, wid, "卷一", "volume")
        vol2 = _make_node(db, wid, "卷二", "volume")
        plot = _make_node(db, wid, "情节", "plot")

        assert json.loads(nt._create_edge_sync(vol1.id, plot.id, edge_type="包含"))["success"] is True
        result = json.loads(nt._create_edge_sync(vol2.id, plot.id, edge_type="包含"))
        assert "error" in result
    finally:
        db.close()


def test_create_edge_tool_allows_chapter_sequence(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        wid = work.id
        ch1 = _make_node(db, wid, "第一章", "chapter")
        ch2 = _make_node(db, wid, "第二章", "chapter")

        result = json.loads(nt._create_edge_sync(ch1.id, ch2.id, edge_type="接续"))
        assert result["success"] is True
    finally:
        db.close()


def test_batch_create_edges_reports_structural_error(monkeypatch):
    """批量创建遇到非法结构时必须报错，不能静默跳过。"""
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        wid = work.id
        outline = _make_node(db, wid, "大纲", "outline")
        ch = _make_node(db, wid, "第一章", "chapter")

        result = json.loads(nt._batch_create_edges_sync([
            {"source_id": outline.id, "target_id": ch.id, "edge_type": "包含"},
        ]))
        assert "error" in result
    finally:
        db.close()
