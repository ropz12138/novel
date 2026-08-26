"""根据节点位置自动计算连线起止边（source_side / target_side）。"""
from models.node import Node

from constants import NODE_WIDTH, NODE_HEIGHT, ELEMENT_WIDTH, ELEMENT_HEIGHT

DEFAULT_NODE_WIDTH = float(NODE_WIDTH)
DEFAULT_NODE_HEIGHT = float(NODE_HEIGHT)

VALID_SIDES = frozenset({"top", "right", "bottom", "left"})
HIERARCHY_CHAIN_TYPES = frozenset({"outline", "volume", "plot", "chapter"})


def is_hierarchy_chain_edge(source: Node, target: Node) -> bool:
    return source.type in HIERARCHY_CHAIN_TYPES and target.type in HIERARCHY_CHAIN_TYPES


def resolve_hierarchy_chain_sides() -> dict[str, str]:
    """结构层级链节点之间固定：源下边界 → 目标上边界。"""
    return {"source_side": "bottom", "target_side": "top"}


def is_chapter_sequence_edge(source: Node, target: Node) -> bool:
    return source.type == "chapter" and target.type == "chapter"


def resolve_chapter_sequence_sides() -> dict[str, str]:
    """章节顺序连线固定：源右边界 → 目标左边界。"""
    return {"source_side": "right", "target_side": "left"}


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
    if is_chapter_sequence_edge(source, target):
        return resolve_chapter_sequence_sides()
    if is_hierarchy_chain_edge(source, target):
        return resolve_hierarchy_chain_sides()

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
