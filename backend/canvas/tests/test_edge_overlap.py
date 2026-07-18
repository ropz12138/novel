"""线-线平行重叠检测测试 — TDD。

只校验"多条连线同方向（都水平或都垂直）且位置重合、区间相交"的平行覆盖；
不校验线-线交叉（相交于一点）、不校验线穿过节点。
阈值：同一垂线 = 4 端点 x 差 < NODE_WIDTH/2；同一水平线 = y 差 < NODE_HEIGHT/2。
共端点的两条线也算候选（共端点 + 同方向会重叠）。
"""
from types import SimpleNamespace

from app.constants import NODE_WIDTH, NODE_HEIGHT
from app.services.agents.node_layout import detect_edge_overlap


def _node(id, x, y, title=None):
    return SimpleNamespace(id=id, position_x=x, position_y=y, title=title or id)


def _edge(s, t):
    return SimpleNamespace(source_id=s, target_id=t)


def test_vertical_overlap_reported():
    # 第一卷、四卷、末日道途 同在 x=100 的垂线上；两条线都到「末日道途」
    nodes = [
        _node("第一卷", 100, 0, "第一卷"),
        _node("四卷", 100, 500, "四卷"),
        _node("末日道途", 100, 1000, "末日道途"),
    ]
    edges = [_edge("第一卷", "末日道途"), _edge("四卷", "末日道途")]
    warnings = detect_edge_overlap(nodes, edges)
    assert len(warnings) == 1
    assert "垂直" in warnings[0]
    assert "第一卷" in warnings[0] and "四卷" in warnings[0]


def test_horizontal_overlap_reported():
    nodes = [
        _node("A", 0, 200, "A"),
        _node("B", 1000, 200, "B"),
        _node("C", 500, 200, "C"),
    ]
    edges = [_edge("A", "B"), _edge("C", "B")]  # x[0,1000] 与 x[500,1000] 重叠
    warnings = detect_edge_overlap(nodes, edges)
    assert len(warnings) == 1
    assert "水平" in warnings[0]


def test_crossing_lines_not_reported():
    # 一条垂直、一条水平，在中间相交 —— 不报
    nodes = [
        _node("A", 100, 0), _node("B", 100, 1000),   # 垂直线 A→B
        _node("C", 0, 500), _node("D", 1000, 500),   # 水平线 C→D
    ]
    edges = [_edge("A", "B"), _edge("C", "D")]
    assert detect_edge_overlap(nodes, edges) == []


def test_shared_endpoint_overlap_reported():
    # 两条线共享起点 A，且终点同垂线 → 共端点也算重叠
    nodes = [
        _node("A", 100, 0, "A"),
        _node("B", 100, 500, "B"),
        _node("C", 100, 1000, "C"),
    ]
    edges = [_edge("A", "B"), _edge("A", "C")]
    warnings = detect_edge_overlap(nodes, edges)
    assert len(warnings) == 1
    assert "垂直" in warnings[0]


def test_same_direction_disjoint_not_reported():
    # 同垂线但 y 区间不重叠（错开）→ 不报
    nodes = [
        _node("A", 100, 0), _node("B", 100, 200),
        _node("C", 100, 500), _node("D", 100, 700),
    ]
    edges = [_edge("A", "B"), _edge("C", "D")]
    assert detect_edge_overlap(nodes, edges) == []


def test_not_aligned_not_reported():
    # 斜线、端点散布 → 不报
    nodes = [
        _node("A", 0, 0), _node("B", 500, 800),
        _node("C", 300, 100), _node("D", 900, 600),
    ]
    edges = [_edge("A", "B"), _edge("C", "D")]
    assert detect_edge_overlap(nodes, edges) == []


def test_missing_endpoint_skipped():
    nodes = [_node("A", 100, 0), _node("B", 100, 500)]
    edges = [_edge("A", "B"), _edge("A", "不存在")]
    # 第二条线端点缺失应跳过，不报错、不报重叠（只一条有效线）
    assert detect_edge_overlap(nodes, edges) == []


def test_threshold_uses_half_node_size():
    # x 差正好 < NODE_WIDTH/2 才算同一垂线；略大于阈值不算
    nodes = [
        _node("A", 0, 0), _node("B", 0, 500),
        _node("C", NODE_WIDTH / 2 + 50, 0), _node("D", NODE_WIDTH / 2 + 50, 500),
    ]
    edges = [_edge("A", "B"), _edge("C", "D")]
    # 两组 x 相差 > NODE_WIDTH/2 → 不视为同一垂线 → 不报
    assert detect_edge_overlap(nodes, edges) == []


# ---------- 工具集成：create_edge 返回线重叠 layout_warnings ----------

import importlib
import json

from app import database
from app.models.user import User
from app.models.work import CanvasWork
from app.models.node import Node as NodeModel

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


def test_create_edge_returns_overlap_warning(monkeypatch):
    db = database.SessionLocal()
    try:
        work = _make_work(monkeypatch, db)
        # 三个垂直排列的节点（作品78 那种：卷 + 末日道途 同垂线）
        a = NodeModel(work_id=work.id, type="volume", title="第一卷", layer=0,
                      position_x=100, position_y=0)
        b = NodeModel(work_id=work.id, type="volume", title="四卷", layer=0,
                      position_x=100, position_y=500)
        c = NodeModel(work_id=work.id, type="outline", title="末日道途", layer=0,
                      position_x=100, position_y=1000)
        db.add_all([a, b, c])
        db.commit()

        r1 = json.loads(nt._create_edge_sync(a.id, c.id, edge_type="包含"))
        assert r1["success"] is True
        assert r1["layout_warnings"] == []  # 只有一条线，无重叠

        r2 = json.loads(nt._create_edge_sync(b.id, c.id, edge_type="包含"))
        assert r2["success"] is True
        assert any("垂直" in w for w in r2["layout_warnings"])
        assert any("第一卷" in w and "四卷" in w for w in r2["layout_warnings"])
    finally:
        db.close()
