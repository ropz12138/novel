"""节点矩形布局诊断的单一事实来源。"""
import math

from constants import NODE_HEIGHT, NODE_WIDTH, ELEMENT_WIDTH, ELEMENT_HEIGHT


TIGHT_THRESHOLD = 10
MIN_GAP_THRESHOLD = 50


def node_rect(node) -> dict:
    x = node.position_x or 0.0
    y = node.position_y or 0.0
    if getattr(node, "type", None) == "element":
        return {
            "id": node.id,
            "title": node.title,
            "x": x,
            "y": y,
            "width": ELEMENT_WIDTH,
            "height": ELEMENT_HEIGHT,
            "shape": "circle",
            "radius": min(ELEMENT_WIDTH, ELEMENT_HEIGHT) / 2,
        }
    return {
        "id": node.id,
        "title": node.title,
        "x": x,
        "y": y,
        "width": NODE_WIDTH,
        "height": NODE_HEIGHT,
        "shape": "rect",
    }


def _circle_center(rect: dict) -> tuple[float, float]:
    return (rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)


def _distance_point_rect(px: float, py: float, rect: dict) -> float:
    """点到矩形最近点的距离（0 表示点在矩形内）。"""
    left = rect["x"]
    right = left + rect["width"]
    top = rect["y"]
    bottom = top + rect["height"]
    dx = max(left - px, 0.0, px - right)
    dy = max(top - py, 0.0, py - bottom)
    return math.hypot(dx, dy)


def _surface_distance(rect_a: dict, rect_b: dict) -> float:
    """
    两形状外表面之间的最近距离（< 0 表示重叠）。
    支持圆-圆、圆-矩形、矩形-矩形。圆通过 rect["shape"]=="circle" 标识。
    """
    a_circle = rect_a.get("shape") == "circle"
    b_circle = rect_b.get("shape") == "circle"
    if a_circle and b_circle:
        ax, ay = _circle_center(rect_a)
        bx, by = _circle_center(rect_b)
        return math.hypot(ax - bx, ay - by) - rect_a["radius"] - rect_b["radius"]
    if a_circle:
        ax, ay = _circle_center(rect_a)
        return _distance_point_rect(ax, ay, rect_b) - rect_a["radius"]
    if b_circle:
        bx, by = _circle_center(rect_b)
        return _distance_point_rect(bx, by, rect_a) - rect_b["radius"]
    # 矩形-矩形：用 AABB 间隙
    a_left, a_right = rect_a["x"], rect_a["x"] + rect_a["width"]
    a_top, a_bottom = rect_a["y"], rect_a["y"] + rect_a["height"]
    b_left, b_right = rect_b["x"], rect_b["x"] + rect_b["width"]
    b_top, b_bottom = rect_b["y"], rect_b["y"] + rect_b["height"]
    gap_x = max(0.0, max(a_left, b_left) - min(a_right, b_right))
    gap_y = max(0.0, max(a_top, b_top) - min(a_bottom, b_bottom))
    return math.hypot(gap_x, gap_y)


def detect_rect_issue(rect_a: dict, rect_b: dict) -> dict | None:
    # 矩形-矩形走原 AABB 逻辑（保留 overlap_width/overlap_height 指标供提示）
    a_circle = rect_a.get("shape") == "circle"
    b_circle = rect_b.get("shape") == "circle"
    if not (a_circle or b_circle):
        a_left = rect_a["x"]
        a_right = a_left + rect_a["width"]
        a_top = rect_a["y"]
        a_bottom = a_top + rect_a["height"]
        b_left = rect_b["x"]
        b_right = b_left + rect_b["width"]
        b_top = rect_b["y"]
        b_bottom = b_top + rect_b["height"]
        overlap_x = max(0.0, min(a_right, b_right) - max(a_left, b_left))
        overlap_y = max(0.0, min(a_bottom, b_bottom) - max(a_top, b_top))
        gap_x = max(0.0, max(a_left, b_left) - min(a_right, b_right))
        gap_y = max(0.0, max(a_top, b_top) - min(a_bottom, b_bottom))
        distance = math.hypot(gap_x, gap_y)
        metrics = {
            "overlap_width": round(overlap_x, 1),
            "overlap_height": round(overlap_y, 1),
            "horizontal_gap": round(gap_x, 1),
            "vertical_gap": round(gap_y, 1),
            "edge_distance": round(distance, 1),
        }
        if overlap_x > 0 and overlap_y > 0:
            return {"type": "overlap", "message": "存在重叠", **metrics}
        if distance <= TIGHT_THRESHOLD:
            return {"type": "touching", "message": "边界紧贴", **metrics}
        if distance < MIN_GAP_THRESHOLD:
            return {
                "type": "too_close",
                "message": f"间距过小（当前约 {distance:.0f}px，建议至少 {MIN_GAP_THRESHOLD}px）",
                **metrics,
            }
        return None

    # 涉及圆形：按真实表面距离判断
    distance = _surface_distance(rect_a, rect_b)
    metrics = {
        "overlap_width": 0.0,
        "overlap_height": 0.0,
        "horizontal_gap": 0.0,
        "vertical_gap": 0.0,
        "edge_distance": round(max(distance, 0.0), 1),
    }
    if distance < 0:
        return {"type": "overlap", "message": "存在重叠", **metrics}
    if distance <= TIGHT_THRESHOLD:
        return {"type": "touching", "message": "边界紧贴", **metrics}
    if distance < MIN_GAP_THRESHOLD:
        return {
            "type": "too_close",
            "message": f"间距过小（当前约 {distance:.0f}px，建议至少 {MIN_GAP_THRESHOLD}px）",
            **metrics,
        }
    return None


def detect_edge_overlap(nodes, edges) -> list[str]:
    """检测连线间的平行覆盖（同方向、同位置、区间相交）。

    只反馈"多条线都水平/垂直对齐且区间重叠"的平行覆盖（视觉上线压线）；
    不校验线-线交叉（相交于一点）、不校验线穿过节点。
    共端点的两条线也参与判定（共端点 + 同方向会重叠）。

    Args:
        nodes: Node 对象列表（含 id/position_x/position_y/title）
        edges: Edge 对象列表（含 source_id/target_id）

    Returns:
        自然语言警告字符串列表
    """
    rect_map = {n.id: node_rect(n) for n in nodes}

    def center(nid):
        r = rect_map.get(nid)
        if not r:
            return None
        return (r["x"] + r["width"] / 2, r["y"] + r["height"] / 2, r["title"])

    lines = []
    for e in edges:
        s = center(getattr(e, "source_id", None))
        t = center(getattr(e, "target_id", None))
        if not s or not t:
            continue
        lines.append({
            "sx": s[0], "sy": s[1], "stitle": s[2],
            "tx": t[0], "ty": t[1], "ttitle": t[2],
        })

    warnings = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            l1, l2 = lines[i], lines[j]
            # 垂直重叠：4 端点 x 都相近 + y 区间相交
            xs = [l1["sx"], l1["tx"], l2["sx"], l2["tx"]]
            if max(xs) - min(xs) < NODE_WIDTH / 2:
                y1_lo, y1_hi = sorted([l1["sy"], l1["ty"]])
                y2_lo, y2_hi = sorted([l2["sy"], l2["ty"]])
                if y1_lo < y2_hi and y2_lo < y1_hi:
                    warnings.append(
                        f"线「{l1['stitle']}→{l1['ttitle']}」与「{l2['stitle']}→{l2['ttitle']}」垂直方向重叠，建议错开节点 x 坐标或调整连线端点"
                    )
                    continue
            # 水平重叠：4 端点 y 都相近 + x 区间相交
            ys = [l1["sy"], l1["ty"], l2["sy"], l2["ty"]]
            if max(ys) - min(ys) < NODE_HEIGHT / 2:
                x1_lo, x1_hi = sorted([l1["sx"], l1["tx"]])
                x2_lo, x2_hi = sorted([l2["sx"], l2["tx"]])
                if x1_lo < x2_hi and x2_lo < x1_hi:
                    warnings.append(
                        f"线「{l1['stitle']}→{l1['ttitle']}」与「{l2['stitle']}→{l2['ttitle']}」水平方向重叠，建议错开节点 y 坐标或调整连线端点"
                    )
    return warnings
