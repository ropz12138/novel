/**
 * vis-network 稳定化完成前的 loading 遮罩最长等待时间（毫秒）。
 * 节点越多、物理模拟越久，适当延长；无节点时立即结束。
 */
export function relationGraphStabilizationFallbackMs(nodeCount, physicsEnabled) {
  if (nodeCount <= 0) return 0;
  if (!physicsEnabled) return 300;
  return Math.min(10000, 1500 + nodeCount * 35);
}

/** @typedef {"script" | "layout" | "stabilize"} RelationGraphLoadingPhase */

/**
 * @param {RelationGraphLoadingPhase | string} phase
 */
export function getRelationGraphLoadingMessage(phase) {
  if (phase === "script") return "正在加载图谱引擎…";
  if (phase === "layout") return "正在构建关系网络…";
  if (phase === "stabilize") return "正在稳定节点布局…";
  return "关系图谱加载中…";
}
