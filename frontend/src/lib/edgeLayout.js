import {
  anchorOnOuterBoundary,
  nodeBoundsFromFlowNode,
} from "./nodeDimensions";

const SIDE_VECTORS = {
  top: { x: 0, y: -1 },
  right: { x: 1, y: 0 },
  bottom: { x: 0, y: 1 },
  left: { x: -1, y: 0 },
};

export const HIERARCHY_CHAIN_TYPES = new Set(["outline", "volume", "plot", "chapter"]);

export function isHierarchyChainEdge(sourceNode, targetNode) {
  const sourceType = sourceNode?.data?.type;
  const targetType = targetNode?.data?.type;
  return HIERARCHY_CHAIN_TYPES.has(sourceType) && HIERARCHY_CHAIN_TYPES.has(targetType);
}

export function resolveHierarchyChainSides() {
  return { source_side: "bottom", target_side: "top" };
}

export function isChapterSequenceEdge(sourceNode, targetNode) {
  return sourceNode?.data?.type === "chapter" && targetNode?.data?.type === "chapter";
}

export function resolveChapterSequenceSides() {
  return { source_side: "right", target_side: "left" };
}

export function normalizeEdgeLayout(extraData = {}) {
  const layout = extraData?.layout || {};
  return {
    source_side: layout.source_side || "bottom",
    target_side: layout.target_side || "top",
    curvature: Number.isFinite(layout.curvature) ? layout.curvature : 0,
    lane: Number.isFinite(layout.lane) ? layout.lane : 0,
    routing_offset: Number.isFinite(layout.routing_offset)
      ? layout.routing_offset
      : null,
    manually_positioned: Boolean(layout.manually_positioned),
  };
}

function nodeBounds(node) {
  return nodeBoundsFromFlowNode(node);
}

export function resolveOptimalSides(sourceNode, targetNode) {
  if (isChapterSequenceEdge(sourceNode, targetNode)) {
    return resolveChapterSequenceSides();
  }
  if (isHierarchyChainEdge(sourceNode, targetNode)) {
    return resolveHierarchyChainSides();
  }

  const sourceBounds = nodeBounds(sourceNode);
  const targetBounds = nodeBounds(targetNode);
  const sx = sourceBounds.x + sourceBounds.width / 2;
  const sy = sourceBounds.y + sourceBounds.height / 2;
  const tx = targetBounds.x + targetBounds.width / 2;
  const ty = targetBounds.y + targetBounds.height / 2;
  const dx = tx - sx;
  const dy = ty - sy;

  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx >= 0
      ? { source_side: "right", target_side: "left" }
      : { source_side: "left", target_side: "right" };
  }
  return dy >= 0
    ? { source_side: "bottom", target_side: "top" }
    : { source_side: "top", target_side: "bottom" };
}

export function edgeHandlesFromSides(sides, { relation = false } = {}) {
  const prefix = relation ? "rel-" : "";
  return {
    sourceHandle: `${prefix}source-${sides.source_side}`,
    targetHandle: `${prefix}target-${sides.target_side}`,
  };
}

export function applyEdgeHandles(nodes, edges, { relation = false } = {}) {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  return edges.map((edge) => {
    const source = nodeMap.get(edge.source);
    const target = nodeMap.get(edge.target);
    if (!source || !target) return edge;
    const handles = edgeHandlesFromSides(
      resolveOptimalSides(source, target),
      { relation },
    );
    return { ...edge, ...handles };
  });
}

function anchorForSide(bounds, side) {
  return anchorOnOuterBoundary(bounds, side);
}

export function getBezierGeometry({
  sourceX,
  sourceY,
  targetX,
  targetY,
  layout,
}) {
  const normalized = normalizeEdgeLayout({ layout });
  const sourceVector = SIDE_VECTORS[normalized.source_side];
  const targetVector = SIDE_VECTORS[normalized.target_side];
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const offset = normalized.routing_offset ?? Math.min(180, Math.max(55, distance * 0.32));
  const normal = { x: -dy / distance, y: dx / distance };
  const bend = normalized.curvature * Math.min(distance, 420) * 0.45
    + normalized.lane * 30;

  const p0 = { x: sourceX, y: sourceY };
  const p1 = {
    x: sourceX + sourceVector.x * offset + normal.x * bend,
    y: sourceY + sourceVector.y * offset + normal.y * bend,
  };
  const p2 = {
    x: targetX + targetVector.x * offset + normal.x * bend,
    y: targetY + targetVector.y * offset + normal.y * bend,
  };
  const p3 = { x: targetX, y: targetY };
  return { p0, p1, p2, p3 };
}

export function pointOnBezier(geometry, t) {
  const u = 1 - t;
  const { p0, p1, p2, p3 } = geometry;
  return {
    x: u ** 3 * p0.x + 3 * u ** 2 * t * p1.x + 3 * u * t ** 2 * p2.x + t ** 3 * p3.x,
    y: u ** 3 * p0.y + 3 * u ** 2 * t * p1.y + 3 * u * t ** 2 * p2.y + t ** 3 * p3.y,
  };
}

function geometryForEdge(nodeMap, edge) {
  const source = nodeMap.get(edge.source);
  const target = nodeMap.get(edge.target);
  if (!source || !target) return null;
  const sides = resolveOptimalSides(source, target);
  const layout = {
    ...normalizeEdgeLayout(edge.data?.extra_data),
    source_side: sides.source_side,
    target_side: sides.target_side,
  };
  const sourcePoint = anchorForSide(nodeBounds(source), layout.source_side);
  const targetPoint = anchorForSide(nodeBounds(target), layout.target_side);
  return getBezierGeometry({
    sourceX: sourcePoint.x,
    sourceY: sourcePoint.y,
    targetX: targetPoint.x,
    targetY: targetPoint.y,
    layout,
  });
}

function rectOverlapArea(a, b) {
  const width = Math.max(0, Math.min(a.right, b.right) - Math.max(a.x, b.x));
  const height = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.y, b.y));
  return width * height;
}

function labelRect(point, label) {
  const width = Math.min(180, Math.max(72, String(label || "").length * 7 + 24));
  const height = 30;
  return {
    x: point.x - width / 2,
    y: point.y - height / 2,
    right: point.x + width / 2,
    bottom: point.y + height / 2,
    width,
    height,
  };
}

export function applyEdgeLabelAvoidance(nodes, edges) {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const nodeRects = nodes.map(nodeBounds);
  const occupiedLabels = [];

  return edges.map((edge) => {
    if (!edge.label) return edge;
    const geometry = geometryForEdge(nodeMap, edge);
    if (!geometry) return edge;
    const dx = geometry.p3.x - geometry.p0.x;
    const dy = geometry.p3.y - geometry.p0.y;
    const distance = Math.max(1, Math.hypot(dx, dy));
    const normal = { x: -dy / distance, y: dx / distance };
    const candidates = [];
    for (const t of [0.5, 0.35, 0.65]) {
      const base = pointOnBezier(geometry, t);
      for (const offset of [0, 30, -30, 60, -60, 90, -90]) {
        candidates.push({
          x: base.x + normal.x * offset,
          y: base.y + normal.y * offset,
        });
      }
    }

    let best = candidates[0];
    let bestRect = labelRect(best, edge.label);
    let bestScore = Number.POSITIVE_INFINITY;
    for (const candidate of candidates) {
      const rect = labelRect(candidate, edge.label);
      const nodePenalty = nodeRects.reduce(
        (sum, nodeRect) => sum + rectOverlapArea(rect, nodeRect) * 4,
        0,
      );
      const labelPenalty = occupiedLabels.reduce(
        (sum, otherRect) => sum + rectOverlapArea(rect, otherRect) * 8,
        0,
      );
      const score = nodePenalty + labelPenalty;
      if (score < bestScore) {
        best = candidate;
        bestRect = rect;
        bestScore = score;
        if (score === 0) break;
      }
    }
    occupiedLabels.push(bestRect);
    return {
      ...edge,
      data: {
        ...edge.data,
        label_position: best,
        label_collision_score: bestScore,
      },
    };
  });
}
