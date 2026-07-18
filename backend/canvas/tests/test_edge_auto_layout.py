"""连线起止点自动计算 — TDD

create_edge / batch_create_edges 根据节点位置自动写入 layout.source_side / target_side；
工具入参不再接受 source_side / target_side。
"""
import importlib
import json

from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node
from app.models.edge import Edge
from app.services.edge_layout_service import resolve_optimal_sides, is_hierarchy_chain_edge

nt = importlib.import_module("app.services.agents.tools.node_tools")


def _make_work(monkeypatch, db):
    user = User(username="t", email="t@t.t", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="w")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def _make_node(db, work_id, title="n", x=0.0, y=0.0, node_type="outline"):
    node = Node(
        work_id=work_id,
        type=node_type,
        title=title,
        layer=0,
        position_x=x,
        position_y=y,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def test_resolve_optimal_sides_vertical():
    source = Node(position_x=0, position_y=0)
    target = Node(position_x=0, position_y=300)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "bottom",
        "target_side": "top",
    }


def test_resolve_optimal_sides_vertical_reverse():
    source = Node(position_x=0, position_y=300)
    target = Node(position_x=0, position_y=0)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "top",
        "target_side": "bottom",
    }


def test_resolve_optimal_sides_horizontal():
    source = Node(position_x=0, position_y=0)
    target = Node(position_x=400, position_y=0)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "right",
        "target_side": "left",
    }


def test_resolve_optimal_sides_horizontal_reverse():
    source = Node(position_x=400, position_y=0)
    target = Node(position_x=0, position_y=0)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "left",
        "target_side": "right",
    }


def test_hierarchy_chain_forces_bottom_to_top_even_when_horizontal():
    source = Node(type="outline", position_x=0, position_y=0)
    target = Node(type="volume", position_x=500, position_y=0)
    assert is_hierarchy_chain_edge(source, target) is True
    assert resolve_optimal_sides(source, target) == {
        "source_side": "bottom",
        "target_side": "top",
    }


def test_hierarchy_chain_plot_to_chapter():
    source = Node(type="plot", position_x=100, position_y=200)
    target = Node(type="chapter", position_x=100, position_y=500)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "bottom",
        "target_side": "top",
    }


def test_chapter_to_chapter_forces_right_to_left():
    source = Node(type="chapter", position_x=640, position_y=817)
    target = Node(type="chapter", position_x=992, position_y=824)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "right",
        "target_side": "left",
    }


def test_create_edge_chapter_sequence_layout_right_left(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        wid = nt._get_current_work_id()
        ch1 = _make_node(db, wid, "第一章", x=640, y=817, node_type="chapter")
        ch2 = _make_node(db, wid, "第二章", x=992, y=824, node_type="chapter")

        result = json.loads(nt._create_edge_sync(ch1.id, ch2.id, edge_type="next_chapter"))

        assert result["success"] is True
        edge = db.query(Edge).filter(Edge.source_id == ch1.id).first()
        assert edge.extra_data["layout"]["source_side"] == "right"
        assert edge.extra_data["layout"]["target_side"] == "left"
    finally:
        db.close()


def test_mixed_chain_and_element_uses_position():
    source = Node(type="element", position_x=0, position_y=0)
    target = Node(type="chapter", position_x=400, position_y=0)
    assert is_hierarchy_chain_edge(source, target) is False
    assert resolve_optimal_sides(source, target) == {
        "source_side": "right",
        "target_side": "left",
    }


def test_element_uses_smaller_dimensions_for_side_choice():
    """element 90×90 时中心偏移；若仍按 250×120 算，近对角会误判为纵向连接"""
    elem = Node(type="element", position_x=0, position_y=0)
    ch = Node(type="chapter", position_x=50, position_y=100)
    assert resolve_optimal_sides(elem, ch) == {
        "source_side": "right",
        "target_side": "left",
    }


def test_create_edge_hierarchy_chain_layout_bottom_top(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        wid = nt._get_current_work_id()
        outline = _make_node(db, wid, "大纲", x=0, y=0, node_type="outline")
        volume = _make_node(db, wid, "第一卷", x=500, y=0, node_type="volume")

        result = json.loads(nt._create_edge_sync(outline.id, volume.id, edge_type="contains"))

        assert result["success"] is True
        edge = db.query(Edge).filter(Edge.source_id == outline.id).first()
        assert edge.extra_data["layout"]["source_side"] == "bottom"
        assert edge.extra_data["layout"]["target_side"] == "top"
    finally:
        db.close()


def test_create_edge_auto_layout_horizontal(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        wid = nt._get_current_work_id()
        elem = _make_node(db, wid, "元素", x=0, y=0, node_type="element")
        ch = _make_node(db, wid, "章", x=400, y=0, node_type="chapter")

        result = json.loads(nt._create_edge_sync(elem.id, ch.id, edge_type="contains"))

        assert result["success"] is True
        edge = db.query(Edge).filter(Edge.source_id == elem.id).first()
        assert edge.extra_data["layout"]["source_side"] == "right"
        assert edge.extra_data["layout"]["target_side"] == "left"
    finally:
        db.close()


def test_create_edge_auto_layout_vertical(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        wid = nt._get_current_work_id()
        a = _make_node(db, wid, "A", x=0, y=0)
        b = _make_node(db, wid, "B", x=0, y=300)

        result = json.loads(nt._create_edge_sync(a.id, b.id, edge_type="包含"))

        assert result["success"] is True
        edge = db.query(Edge).filter(Edge.source_id == a.id).first()
        assert edge.extra_data["layout"]["source_side"] == "bottom"
        assert edge.extra_data["layout"]["target_side"] == "top"
    finally:
        db.close()


def test_batch_create_edges_auto_layout(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        wid = nt._get_current_work_id()
        elem = _make_node(db, wid, "元素", x=0, y=0, node_type="element")
        ch = _make_node(db, wid, "章", x=400, y=0, node_type="chapter")

        result = json.loads(nt._batch_create_edges_sync([
            {"source_id": elem.id, "target_id": ch.id, "edge_type": "contains"},
        ]))

        assert result["success"] is True
        edge = db.query(Edge).filter(Edge.source_id == elem.id).first()
        assert edge.extra_data["layout"]["source_side"] == "right"
        assert edge.extra_data["layout"]["target_side"] == "left"
    finally:
        db.close()


def test_update_edge_preserves_auto_layout(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        wid = nt._get_current_work_id()
        elem = _make_node(db, wid, "元素", x=0, y=0, node_type="element")
        ch = _make_node(db, wid, "章", x=400, y=0, node_type="chapter")

        nt._create_edge_sync(elem.id, ch.id, edge_type="contains")
        edge = db.query(Edge).filter(Edge.source_id == elem.id).first()

        result = json.loads(nt._update_edge_sync(edge.id, label="新标签"))

        assert result["success"] is True
        db.refresh(edge)
        assert edge.label == "新标签"
        assert edge.extra_data["layout"]["source_side"] == "right"
        assert edge.extra_data["layout"]["target_side"] == "left"
    finally:
        db.close()
