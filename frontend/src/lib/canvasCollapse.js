/** 画布收起/展开：结构树（contains）与章节关联元素 */

export const CONTAINS_EDGE_TYPES = new Set(["contains", "包含"]);

export function isContainsEdge(edgeType) {
  return CONTAINS_EDGE_TYPES.has((edgeType || "").trim());
}

export function isDescendantOfCollapsed(nodeId, parentMap, collapsedNodeIds) {
  let cur = parentMap[nodeId];
  while (cur) {
    if (collapsedNodeIds.has(cur)) return true;
    cur = parentMap[cur];
  }
  return false;
}

export function buildContainsParentMap(edges) {
  const parentMap = {};
  for (const edge of edges) {
    if (isContainsEdge(edge.data?.edge_type)) {
      parentMap[edge.target] = edge.source;
    }
  }
  return parentMap;
}

export function buildContainsChildSources(edges) {
  const childSources = new Set();
  for (const edge of edges) {
    if (isContainsEdge(edge.data?.edge_type)) {
      childSources.add(edge.source);
    }
  }
  return childSources;
}

/** element→chapter 的 contains 连线索引 */
export function buildElementChapterLinks(edges, nodes) {
  const typeById = new Map(nodes.map((n) => [n.id, n.data?.type]));
  const elementToChapters = {};
  const chapterToElements = {};

  for (const edge of edges) {
    if (!isContainsEdge(edge.data?.edge_type)) continue;
    const srcType = typeById.get(edge.source);
    const tgtType = typeById.get(edge.target);
    if (srcType !== "element" || tgtType !== "chapter") continue;

    if (!elementToChapters[edge.source]) elementToChapters[edge.source] = [];
    elementToChapters[edge.source].push(edge.target);

    if (!chapterToElements[edge.target]) chapterToElements[edge.target] = [];
    chapterToElements[edge.target].push(edge.source);
  }

  return { elementToChapters, chapterToElements };
}

/**
 * 跨章复用的 element：仅当所有关联章节都已收起时才隐藏。
 */
export function isElementHiddenByCollapsedChapters(
  elementId,
  elementToChapters,
  collapsedNodeIds,
) {
  const chapters = elementToChapters[elementId];
  if (!chapters?.length) return false;
  return chapters.every((chapterId) => collapsedNodeIds.has(chapterId));
}

export function isNodeHiddenByCollapse(
  nodeId,
  {
    parentMap,
    collapsedNodeIds,
    elementToChapters,
    nodeTypeById,
  },
) {
  if (isDescendantOfCollapsed(nodeId, parentMap, collapsedNodeIds)) {
    return true;
  }
  if (nodeTypeById.get(nodeId) === "element") {
    return isElementHiddenByCollapsedChapters(
      nodeId,
      elementToChapters,
      collapsedNodeIds,
    );
  }
  return false;
}

export function buildCollapsibleNodeIds(childSources, chapterToElements) {
  const ids = new Set(childSources);
  for (const chapterId of Object.keys(chapterToElements)) {
    if (chapterToElements[chapterId].length > 0) {
      ids.add(chapterId);
    }
  }
  return ids;
}
