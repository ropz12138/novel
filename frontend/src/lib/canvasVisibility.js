/**
 * 可见子图投影。
 *
 * 隐藏是投影结果，不是删除：完整语义图始终保留在 allNodes / allEdges 中，
 * 这里只决定当前视图渲染哪些节点和边。布局的输入必须是这里的输出，
 * 而不能先布局全部节点再隐藏一部分。
 */
import { hierarchyRootIds, ancestorChain, childIdsOf, hasHierarchyChildren } from "./canvasGraph";
import { isHierarchyEdge, isCanvasStructuralType } from "./canvasRelation";

/** 默认从根节点向下展开的层数：0 只显示根，1 额外显示第一层子节点。 */
export const DEFAULT_EXPAND_DEPTH = 1;

export function isNodeExpandable(index, nodeId) {
  return hasHierarchyChildren(index, nodeId);
}

export function toggleExpanded(expandedNodeIds, nodeId) {
  const next = new Set(expandedNodeIds);
  if (next.has(nodeId)) next.delete(nodeId);
  else next.add(nodeId);
  return next;
}

export function toggleSatelliteExpanded(satelliteExpandedNodeIds, nodeId) {
  const next = new Set(satelliteExpandedNodeIds);
  if (next.has(nodeId)) next.delete(nodeId);
  else next.add(nodeId);
  return next;
}

export function projectVisibleGraph({
  index,
  expandedNodeIds,
  focusNodeId = null,
  satelliteExpandedNodeIds = new Set(),
  defaultExpandDepth = DEFAULT_EXPAND_DEPTH,
}) {
  // 聚焦节点的祖先链视为已展开，使目标节点必然落入可见集合
  const effectiveExpanded = new Set(expandedNodeIds);
  if (focusNodeId) {
    for (const ancestorId of ancestorChain(index, focusNodeId)) {
      effectiveExpanded.add(ancestorId);
    }
  }

  const depthById = new Map();
  const visibleNodeIds = new Set();
  const queue = hierarchyRootIds(index).map((id) => ({ id, depth: 0 }));

  while (queue.length) {
    const { id, depth } = queue.shift();
    if (visibleNodeIds.has(id)) continue;
    visibleNodeIds.add(id);
    depthById.set(id, depth);

    const expanded = effectiveExpanded.has(id) || depth < defaultExpandDepth;
    if (!expanded) continue;
    for (const childId of childIdsOf(index, id)) {
      queue.push({ id: childId, depth: depth + 1 });
    }
  }

  // 卫星节点：不参与树结构的关联节点（如配角），只在用户显式展开相关角色时出现。
  // 与节点详情抽屉解耦：点击节点只打开详情，不会顺带把角色带上画布。
  const satelliteAnchorById = new Map();
  for (const anchorId of satelliteExpandedNodeIds) {
    if (!visibleNodeIds.has(anchorId)) continue;
    for (const edge of index.edges) {
      if (edge.source !== anchorId && edge.target !== anchorId) continue;
      const otherId = edge.source === anchorId ? edge.target : edge.source;
      const otherNode = index.nodeById.get(otherId);
      if (!otherNode) continue;
      // 非结构节点即卫星候选。worldbuilding 与 note 被禁止连线，
      // 在图中没有边，因此不会走到这里。
      if (isCanvasStructuralType(otherNode.data?.type)) continue;
      satelliteAnchorById.set(otherId, anchorId);
      visibleNodeIds.add(otherId);
    }
  }

  const visibleNodes = index.nodes.filter((node) => visibleNodeIds.has(node.id));

  const visibleEdges = index.edges.filter((edge) => {
    if (!visibleNodeIds.has(edge.source) || !visibleNodeIds.has(edge.target)) {
      return false;
    }
    if (isHierarchyEdge(edge, index.typeById)) return true;
    // 非结构关系只在展开相关角色时显示
    for (const anchorId of satelliteExpandedNodeIds) {
      if (edge.source === anchorId || edge.target === anchorId) return true;
    }
    return false;
  });

  return {
    visibleNodes,
    visibleNodeIds,
    visibleEdges,
    depthById,
    satelliteAnchorById,
    effectiveExpanded,
  };
}
