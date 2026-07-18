import importlib
import json

from app import database
from app.constants import NODE_HEIGHT, NODE_WIDTH
from app.models.node import Node
from app.models.user import User
from app.models.work import CanvasWork

nt = importlib.import_module("app.services.agents.tools.node_tools")
qt = importlib.import_module("app.services.agents.tools.query_tools")


def _make_work(monkeypatch, db):
    user = User(username="layout-feedback", email="layout-feedback@test.local", password_hash="x")
    db.add(user)
    db.commit()
    work = CanvasWork(user_id=user.id, title="布局反馈测试")
    db.add(work)
    db.commit()
    monkeypatch.setattr(nt, "_get_current_work_id", lambda: work.id)
    return work


def test_backend_node_dimensions_match_fixed_frontend_dimensions():
    assert NODE_WIDTH == 250
    assert NODE_HEIGHT == 120


def test_element_node_rect_uses_smaller_size():
    """element 节点为圆形小尺寸，布局检测应按 ELEMENT 尺寸算，否则会误判重叠"""
    from types import SimpleNamespace
    from app.constants import ELEMENT_WIDTH, ELEMENT_HEIGHT
    from app.services.agents.node_layout import node_rect

    elem = SimpleNamespace(id="e", title="觉醒", type="element", position_x=0, position_y=0)
    r = node_rect(elem)
    assert r["width"] == ELEMENT_WIDTH
    assert r["height"] == ELEMENT_HEIGHT

    normal = SimpleNamespace(id="n", title="章节", type="chapter", position_x=0, position_y=0)
    rn = node_rect(normal)
    assert rn["width"] == NODE_WIDTH
    assert rn["height"] == NODE_HEIGHT


def test_detects_work_52_horizontal_overlap():
    first_chapter = {"x": 500, "y": 0, "width": NODE_WIDTH, "height": NODE_HEIGHT}
    world_setting = {"x": 700, "y": 0, "width": NODE_WIDTH, "height": NODE_HEIGHT}

    assert nt._detect_rect_issue(first_chapter, world_setting) == "存在重叠"


def test_distance_uses_separating_axis_when_other_axis_overlaps():
    upper = {"x": 0, "y": 0, "width": NODE_WIDTH, "height": NODE_HEIGHT}
    safely_below = {"x": 0, "y": 170, "width": NODE_WIDTH, "height": NODE_HEIGHT}
    too_close_below = {"x": 0, "y": 169, "width": NODE_WIDTH, "height": NODE_HEIGHT}

    assert nt._detect_rect_issue(upper, safely_below) == ""
    assert "间距过小" in nt._detect_rect_issue(upper, too_close_below)


def test_create_node_returns_layout_warning(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        db.add(Node(
            work_id=work.id,
            type="setting",
            title="末日世界观：欲望病毒",
            position_x=700,
            position_y=0,
        ))
        db.commit()

        result = json.loads(nt._create_node_sync(
            "chapter",
            "第一章：废墟相遇",
            position_x=500,
            position_y=0,
        ))

        assert result["success"] is True
        assert any("存在重叠" in warning for warning in result["layout_warnings"])
        assert "update_node" in result["layout_hint"]
    finally:
        db.close()


def test_update_node_returns_layout_warning_even_without_coordinate_change(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        chapter = Node(
            work_id=work.id,
            type="chapter",
            title="第一章",
            position_x=500,
            position_y=0,
        )
        setting = Node(
            work_id=work.id,
            type="setting",
            title="末日世界观",
            position_x=700,
            position_y=0,
        )
        db.add_all([chapter, setting])
        db.commit()

        result = json.loads(nt._update_node_sync(chapter.id, title="第一章：废墟相遇"))

        assert result["success"] is True
        assert any("存在重叠" in warning for warning in result["layout_warnings"])
    finally:
        db.close()


def test_get_node_layout_issues_returns_authoritative_pair_metrics(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        monkeypatch.setattr(qt, "_get_current_work_id", lambda: work.id)
        chapter = Node(
            work_id=work.id,
            type="chapter",
            title="第一章：废墟相遇",
            position_x=500,
            position_y=0,
        )
        setting = Node(
            work_id=work.id,
            type="setting",
            title="末日世界观：欲望病毒",
            position_x=700,
            position_y=0,
        )
        db.add_all([chapter, setting])
        db.commit()

        result = json.loads(qt._get_node_layout_issues_sync())

        assert result["total"] == 1
        assert result["counts"]["overlap"] == 1
        assert result["issues"][0]["metrics"]["overlap_width"] == 50
        assert result["issues"][0]["metrics"]["overlap_height"] == 120
        assert result["node_size"] == {"width": 250, "height": 120}
    finally:
        db.close()


def test_get_node_layout_issues_can_filter_by_node(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        monkeypatch.setattr(qt, "_get_current_work_id", lambda: work.id)
        first = Node(
            work_id=work.id, type="idea", title="A",
            position_x=0, position_y=0,
        )
        second = Node(
            work_id=work.id, type="idea", title="B",
            position_x=200, position_y=0,
        )
        distant = Node(
            work_id=work.id, type="idea", title="C",
            position_x=1000, position_y=1000,
        )
        db.add_all([first, second, distant])
        db.commit()

        result = json.loads(qt._get_node_layout_issues_sync(node_id=distant.id))

        assert result["total"] == 0
    finally:
        db.close()


def test_batch_create_nodes_returns_layout_warning_for_overlap_with_existing(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        db.add(Node(
            work_id=work.id,
            type="setting",
            title="末日世界观",
            position_x=700,
            position_y=0,
        ))
        db.commit()

        result = json.loads(nt._batch_create_nodes_sync(nodes_data=[
            {"node_type": "chapter", "title": "第一章", "position_x": 500, "position_y": 0},
        ]))

        assert result["success"] is True
        assert any("存在重叠" in w for w in result["layout_warnings"])
        assert "update_node" in result["layout_hint"]
    finally:
        db.close()


def test_batch_create_nodes_detects_overlap_between_new_nodes(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)

        result = json.loads(nt._batch_create_nodes_sync(nodes_data=[
            {"node_type": "chapter", "title": "第一章", "position_x": 500, "position_y": 0},
            {"node_type": "chapter", "title": "第二章", "position_x": 600, "position_y": 0},
        ]))

        assert result["success"] is True
        # 500+250=750 > 600，两个新节点彼此重叠 150px
        assert any("存在重叠" in w for w in result["layout_warnings"])
    finally:
        db.close()


def test_batch_create_nodes_returns_empty_warnings_when_no_conflict(monkeypatch):
    db = database.SessionLocal()
    try:
        _make_work(monkeypatch, db)

        result = json.loads(nt._batch_create_nodes_sync(nodes_data=[
            {"node_type": "outline", "title": "A", "position_x": 0, "position_y": 0},
            {"node_type": "outline", "title": "B", "position_x": 1000, "position_y": 0},
        ]))

        assert result["success"] is True
        assert result["layout_warnings"] == []
    finally:
        db.close()


def test_layout_warning_is_natural_language_with_node_title(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        db.add(Node(
            work_id=work.id,
            type="setting",
            title="末日世界观：欲望病毒",
            position_x=700,
            position_y=0,
        ))
        db.commit()

        result = json.loads(nt._create_node_sync(
            "chapter", "第一章：废墟相遇",
            position_x=500, position_y=0,
        ))

        # 自然语言警告应包含对方节点标题，便于 agent 定位
        assert any("末日世界观：欲望病毒" in w for w in result["layout_warnings"])
    finally:
        db.close()


def test_get_node_layout_issues_tool_is_registered():
    assert "get_node_layout_issues" in {tool.name for tool in qt.query_tools}
