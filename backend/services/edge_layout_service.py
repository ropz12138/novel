"""根据节点位置自动计算连线起止边（source_side / target_side）。"""
from models.node import Node

from constants import NODE_WIDTH, NODE_HEIGHT, ELEMENT_WIDTH, ELEMENT_HEIGHT

DEFAULT_NODE_WIDTH = float(NODE_WIDTH)
DEFAULT_NODE_HEIGHT = float(NODE_HEIGHT)

VALID_SIDES = frozenset({"top", "right", "bottom", "left"})
def _node_dimensions(node: Node) -> tuple[float, float]:
    if node.type == "element":
        return float(ELEMENT_WIDTH), float(ELEMENT_HEIGHT)
    return DEFAULT_NODE_WIDTH, DEFAULT_NODE_HEIGHT


def _node_center(node: Node) -> tuple[float, float]:
    width, height = _node_dimensions(node)
    cx = float(node.position_x or 0) + width / 2
    cy = float(node.position_y or 0) + height / 2
    return cx, cy


def resolve_optimal_sides(source: Node, target: Node) -> dict[str, str]:
    """根据两节点相对位置选择最自然的连接方向。"""
    sx, sy = _node_center(source)
    tx, ty = _node_center(target)
    dx = tx - sx
    dy = ty - sy

    if abs(dx) >= abs(dy):
        if dx >= 0:
            return {"source_side": "right", "target_side": "left"}
        return {"source_side": "left", "target_side": "right"}

    if dy >= 0:
        return {"source_side": "bottom", "target_side": "top"}
    return {"source_side": "top", "target_side": "bottom"}


def build_edge_layout(source: Node, target: Node) -> dict:
    """构建写入 edges.extra_data 的 layout 字段。"""
    return {"layout": resolve_optimal_sides(source, target)}
