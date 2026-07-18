/** 结构关联线样式：按 edge_type 预设；角色节点发出的线单独配色 */

export const CHARACTER_OUTGOING_EDGE_STYLE = {
  stroke: "#ec4899",
  strokeWidth: 2,
};

const edgeStyles = {
  uses: { stroke: "#3b82f6", strokeWidth: 2 },
  hints: { stroke: "#a855f7", strokeWidth: 1.5, strokeDasharray: "5,5" },
  conflict: { stroke: "#ef4444", strokeWidth: 2 },
  inherits: { stroke: "#22c55e", strokeWidth: 2 },
  contains: { stroke: "#f59e0b", strokeWidth: 2, strokeDasharray: "8,4" },
  reverses: { stroke: "#f97316", strokeWidth: 2, strokeDasharray: "10,5" },
  character_appears: { stroke: "#ec4899", strokeWidth: 1.5 },
  mood: { stroke: "#6366f1", strokeWidth: 1.5 },
  forbids_reveal: { stroke: "#dc2626", strokeWidth: 2.5 },
  _default: { stroke: "#94a3b8", strokeWidth: 1.5 },
};

export function getEdgeStyleByType(edgeType) {
  return edgeStyles[edgeType] || edgeStyles._default;
}

export function getStructuralEdgeStyle(edgeType, sourceNodeType) {
  if (sourceNodeType === "character") {
    return { ...CHARACTER_OUTGOING_EDGE_STYLE };
  }
  return getEdgeStyleByType(edgeType);
}

export function nodeTypeByIdFromFlowNodes(nodes) {
  return new Map(nodes.map((node) => [node.id, node.data?.type]));
}

export function nodeTypeByIdFromRawNodes(nodes) {
  return new Map(nodes.map((node) => [node.id, node.type]));
}
