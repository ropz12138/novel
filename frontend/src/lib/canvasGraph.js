/**
 * 完整语义图的索引：父子关系、根节点、祖先链、子树统计。
 *
 * 父子关系一律通过 canvasRelation 的类型判据推导，不读取 edge_type 文本。
 */
import { isHierarchyEdge, isCanvasStructuralType } from "./canvasRelation";
import { compareSiblings } from "./canvasOrder";

const TYPE_LABELS = {
  outline: { unit: "个大纲" },
  volume: { unit: "卷" },
  plot: { unit: "个情节" },
  chapter: { unit: "章" },
};

const SUMMARY_ORDER = ["volume", "plot", "chapter"];

export function buildGraphIndex(nodes, edges) {
  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const typeById = new Map(nodes.map((n) => [n.id, n.data?.type]));
  const parentById = new Map();
  const childIdsById = new Map();

  for (const edge of edges) {
    if (!isHierarchyEdge(edge, typeById)) continue;
    parentById.set(edge.target, edge.source);
    if (!childIdsById.has(edge.source)) childIdsById.set(edge.source, []);
    childIdsById.get(edge.source).push(edge.target);
  }

  for (const [parentId, childIds] of childIdsById) {
    childIds.sort((a, b) => compareSiblings(nodeById.get(a), nodeById.get(b)));
    childIdsById.set(parentId, childIds);
  }

  return { nodes, edges, nodeById, typeById, parentById, childIdsById };
}

export function childIdsOf(index, nodeId) {
  return index.childIdsById.get(nodeId) ?? [];
}

export function hasHierarchyChildren(index, nodeId) {
  return childIdsOf(index, nodeId).length > 0;
}

/** 结构节点是否有关联的非结构邻居（如章节连到的配角）。 */
export function hasRelatedCharacters(index, nodeId) {
  const node = index.nodeById.get(nodeId);
  if (!node || !isCanvasStructuralType(node.data?.type)) return false;
  for (const edge of index.edges) {
    if (edge.source !== nodeId && edge.target !== nodeId) continue;
    const otherId = edge.source === nodeId ? edge.target : edge.source;
    const otherNode = index.nodeById.get(otherId);
    if (!otherNode) continue;
    if (!isCanvasStructuralType(otherNode.data?.type)) return true;
  }
  return false;
}

/** 没有 hierarchy 父边的层级链节点，构成树或森林的根。 */
export function hierarchyRootIds(index) {
  return index.nodes
    .filter(
      (node) =>
        isCanvasStructuralType(node.data?.type) && !index.parentById.has(node.id),
    )
    .sort(compareSiblings)
    .map((node) => node.id);
}

/** 从直接父节点到根的祖先链。 */
export function ancestorChain(index, nodeId) {
  const chain = [];
  const seen = new Set([nodeId]);
  let current = index.parentById.get(nodeId);
  while (current && !seen.has(current)) {
    chain.push(current);
    seen.add(current);
    current = index.parentById.get(current);
  }
  return chain;
}

export function descendantIds(index, nodeId) {
  const result = [];
  const queue = [...childIdsOf(index, nodeId)];
  const seen = new Set(queue);
  while (queue.length) {
    const current = queue.shift();
    result.push(current);
    for (const childId of childIdsOf(index, current)) {
      if (seen.has(childId)) continue;
      seen.add(childId);
      queue.push(childId);
    }
  }
  return result;
}

function formatSummary(byType) {
  return SUMMARY_ORDER.filter((type) => byType[type])
    .map((type) => `${byType[type]} ${TYPE_LABELS[type]?.unit ?? "个节点"}`)
    .join(" · ");
}

/**
 * 统计该节点有多少后代不在当前可见集合中。
 *
 * 直接以可见集合为判据，而不是从展开集合反推：默认展开深度会让根节点的子节点
 * 可见却并未出现在 expandedNodeIds 中，从展开集合推导会把它们误判为隐藏。
 */
export function hiddenDescendantSummary(index, nodeId, visibleNodeIds) {
  const byType = {};
  let total = 0;

  for (const descendantId of descendantIds(index, nodeId)) {
    if (visibleNodeIds.has(descendantId)) continue;
    total += 1;
    const type = index.typeById.get(descendantId) ?? "unknown";
    byType[type] = (byType[type] ?? 0) + 1;
  }

  return { total, byType, text: formatSummary(byType) };
}
