"""element 节点（圆形）布局几何检测测试。

背景：
- element 节点前端渲染为 90×90 的圆（rounded-full），但 ReactFlow 仍按 90×90 矩形定位（左上角）。
- 其他节点是 250×120 矩形。
- 原实现 detect_rect_issue / detect_edge_overlap 对所有节点都用外接矩形 AABB，
  对圆形 element 会误报重叠，且 edge center 写死了 NODE_WIDTH/HEIGHT 导致连线端点偏移。

本测试覆盖：
1. 两个圆形 element 外接矩形角部相交但圆体不重叠时，不应报 overlap。
2. 圆形 element 与矩形节点角部相交但实际形状不重叠时，不应报 overlap。
3. detect_edge_overlap 中 element 节点中心应按实际 90×90 计算（而非 250×120）。
"""
import math

from app.constants import NODE_WIDTH, NODE_HEIGHT, ELEMENT_WIDTH, ELEMENT_HEIGHT
from app.services.agents.node_layout import node_rect, detect_rect_issue, detect_edge_overlap


class _FakeNode:
    """轻量 node 替身，满足 node_rect / detect_edge_overlap 的字段需求。"""
    def __init__(self, id, type, title, position_x, position_y):
        self.id = id
        self.type = type
        self.title = title
        self.position_x = position_x
        self.position_y = position_y


# ---------- 问题 1：圆-圆外接矩形角部相交但圆体不重叠 ----------

def test_two_circles_corner_rect_overlap_but_no_circle_overlap():
    """
    两个 90×90 element：A 在 (0,0)，B 在 (80,80)。
    外接矩形：x 重叠 10、y 重叠 10 → AABB 判为 overlap。
    但圆心距 = sqrt(80^2+80^2) ≈ 113.1 > 90（直径），圆体并不重叠。
    期望：不应判为 overlap。
    """
    a = _FakeNode("a", "element", "A", 0.0, 0.0)
    b = _FakeNode("b", "element", "B", 80.0, 80.0)
    rect_a = node_rect(a)
    rect_b = node_rect(b)
    # 确认外接矩形确实相交（验证测试场景本身）
    assert rect_a["width"] == ELEMENT_WIDTH
    assert rect_b["width"] == ELEMENT_WIDTH
    # 期望：不报 overlap（可以是 None，或仅 too_close，但绝不能是 overlap）
    issue = detect_rect_issue(rect_a, rect_b)
    assert issue is None or issue["type"] != "overlap", (
        f"圆-圆角部相交不应判为 overlap，实际: {issue}"
    )


def test_two_circles_actually_overlapping_still_reported():
    """
    两个 90×90 element 圆心距 < 90 时确实重叠，应报 overlap。
    A 在 (0,0)，B 在 (50,0)，圆心距 50 < 90。
    """
    a = _FakeNode("a", "element", "A", 0.0, 0.0)
    b = _FakeNode("b", "element", "B", 50.0, 0.0)
    issue = detect_rect_issue(node_rect(a), node_rect(b))
    assert issue is not None
    assert issue["type"] == "overlap"


# ---------- 问题 2：圆-矩形角部相交但实际形状不重叠 ----------

def test_circle_rect_corner_overlap_but_shapes_do_not_touch():
    """
    element 圆 A 在 (0,0)（90×90 圆，圆心 (45,45)，半径 45）。
    矩形节点 B 放在 (80, 100)（250×120 矩形）。
    外接矩形：x 重叠 = 90-80 = 10，y 重叠 = 90-100 < 0 → 实际 y 不重叠。
    为构造 x、y 都轻微相交但圆-矩形不接触的场景，调整 B 到 (85, 85)：
      矩形 B 覆盖 x∈[85,335], y∈[85,205]。
      圆 A 中心 (45,45) 半径 45。矩形最近点为 (85,85)。
      圆心到 (85,85) 距离 = sqrt(40^2+40^2) ≈ 56.6 > 45，圆与矩形不接触。
    外接矩形角部相交（x 重叠 5、y 重叠 5）但形状不接触，不应报 overlap。
    """
    a = _FakeNode("a", "element", "A", 0.0, 0.0)
    b = _FakeNode("b", "outline", "B", 85.0, 85.0)
    rect_a = node_rect(a)
    rect_b = node_rect(b)
    assert rect_a["width"] == ELEMENT_WIDTH
    assert rect_b["width"] == NODE_WIDTH
    issue = detect_rect_issue(rect_a, rect_b)
    assert issue is None or issue["type"] != "overlap", (
        f"圆-矩形角部相交但形状不接触，不应判 overlap，实际: {issue}"
    )


def test_circle_rect_actually_overlapping_still_reported():
    """
    矩形 B 放到圆 A 内部，确实重叠。
    A 圆心 (45,45)，B 在 (40,40) 的矩形必然与圆相交。
    """
    a = _FakeNode("a", "element", "A", 0.0, 0.0)
    b = _FakeNode("b", "outline", "B", 40.0, 40.0)
    issue = detect_rect_issue(node_rect(a), node_rect(b))
    assert issue is not None
    assert issue["type"] == "overlap"


# ---------- 问题 3：detect_edge_overlap 的 element 中心计算 ----------

class _FakeEdge:
    def __init__(self, id, source_id, target_id):
        self.id = id
        self.source_id = source_id
        self.target_id = target_id


def test_edge_overlap_uses_element_actual_center():
    """
    两条 element→outline 垂直线，element 端 x 差 D=60：
      线1: element(0,0) -> outline(0,1000)   element 端真实中心 x=45
      线2: element(60,0) -> outline(60,1000) element 端真实中心 x=105
    端点 x 集合（用实际中心）：{45, 125, 105, 185}，max-min=140 ≥ NODE_WIDTH/2(125) → 不重叠（正确）。
    若 center() 错误地用 NODE_WIDTH/2=125 算 element 端：{125,125,185,185}，max-min=60<125 → 误报重叠。
    所以 D=60 能区分两种实现。
    """
    e1 = _FakeNode("e1", "element", "E1", 0.0, 0.0)
    o1 = _FakeNode("o1", "outline", "O1", 0.0, 1000.0)
    e2 = _FakeNode("e2", "element", "E2", 60.0, 0.0)
    o2 = _FakeNode("o2", "outline", "O2", 60.0, 1000.0)
    nodes = [e1, o1, e2, o2]
    edges = [
        _FakeEdge("l1", "e1", "o1"),
        _FakeEdge("l2", "e2", "o2"),
    ]
    warnings = detect_edge_overlap(nodes, edges)
    assert warnings == [], (
        f"element 端中心应按实际 90 计算，D=60 时两线不应判垂直重叠，实际 warnings={warnings}"
    )


def test_element_rect_dimensions():
    """element 节点 node_rect 应返回 90×90。"""
    e = _FakeNode("e", "element", "E", 10.0, 20.0)
    r = node_rect(e)
    assert r["width"] == ELEMENT_WIDTH
    assert r["height"] == ELEMENT_HEIGHT
    assert r["x"] == 10.0
    assert r["y"] == 20.0


def test_normal_node_rect_dimensions():
    """普通节点 node_rect 应返回 250×120。"""
    n = _FakeNode("n", "outline", "N", 0.0, 0.0)
    r = node_rect(n)
    assert r["width"] == NODE_WIDTH
    assert r["height"] == NODE_HEIGHT
