"""连线起止点自动计算 — TDD

create_edge / batch_create_edges 根据节点位置自动写入 layout.source_side / target_side；
工具入参不再接受 source_side / target_side。
"""
import importlib
import json

import database
from models.user import User
from models.work import CanvasWork
from models.node import Node
from models.edge import Edge
from services.edge_layout_service import resolve_optimal_sides

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


def _make_node(db, work_id, title="n", x=0.0, y=0.0, node_type="outline"):
    node = Node(sort_order=0, 
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
    source = Node(sort_order=0, position_x=0, position_y=0)
    target = Node(sort_order=0, position_x=0, position_y=300)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "bottom",
        "target_side": "top",
    }


def test_resolve_optimal_sides_vertical_reverse():
    source = Node(sort_order=0, position_x=0, position_y=300)
    target = Node(sort_order=0, position_x=0, position_y=0)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "top",
        "target_side": "bottom",
    }


def test_resolve_optimal_sides_horizontal():
    source = Node(sort_order=0, position_x=0, position_y=0)
    target = Node(sort_order=0, position_x=400, position_y=0)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "right",
        "target_side": "left",
    }


def test_resolve_optimal_sides_horizontal_reverse():
    source = Node(sort_order=0, position_x=400, position_y=0)
    target = Node(sort_order=0, position_x=0, position_y=0)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "left",
        "target_side": "right",
    }






def test_mixed_chain_and_element_uses_position():
    source = Node(sort_order=0, type="element", position_x=0, position_y=0)
    target = Node(sort_order=0, type="chapter", position_x=400, position_y=0)
    assert resolve_optimal_sides(source, target) == {
        "source_side": "right",
        "target_side": "left",
    }


def test_element_uses_smaller_dimensions_for_side_choice():
    """element 90×90 时中心偏移；若仍按 250×120 算，近对角会误判为纵向连接"""
    elem = Node(sort_order=0, type="element", position_x=0, position_y=0)
    ch = Node(sort_order=0, type="chapter", position_x=50, position_y=100)
    assert resolve_optimal_sides(elem, ch) == {
        "source_side": "right",
        "target_side": "left",
    }




def test_create_edge_rejects_character_to_chapter(monkeypatch):
    """角色登场不再用画布连线；horizontal 布局用 resolve_optimal_sides 单测覆盖。"""
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)
        wid = nt._get_current_work_id()
        character = _make_node(db, wid, "角色", x=0, y=0, node_type="character")
        ch = _make_node(db, wid, "章", x=400, y=0, node_type="chapter")

        result = json.loads(nt._create_edge_sync(character.id, ch.id, edge_type="参与"))
        assert "error" in result
        assert "characters" in result["error"]
    finally:
        db.close()
