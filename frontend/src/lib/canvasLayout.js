/**
 * 可见子图的自上而下树布局。
 *
 * 输入必须是可见子图，不能先布局全部节点再隐藏一部分，否则隐藏节点会留下空洞。
 *
 * 子树宽度取"自身宽度"与"子节点总宽"的较大值，父节点在子树区间内居中。
 * 这样父节点永远不会溢出自己的子树区间，相邻子树之间的间距即可保证任意两个
 * 节点不重叠，无需额外的重叠修正。
 */
import { childIdsOf } from "./canvasGraph";
import { NODE_WIDTH, NODE_HEIGHT } from "./nodeDimensions";

export const MIN_HORIZONTAL_GAP = 80;
export const MIN_VERTICAL_GAP = 120;
export const ROOT_GAP = 160;

const ROW_HEIGHT = NODE_HEIGHT + MIN_VERTICAL_GAP;

function visibleChildIds(index, nodeId, visibleNodeIds) {
  return childIdsOf(index, nodeId).filter((id) => visibleNodeIds.has(id));
}

function measureSubtree(index, nodeId, visibleNodeIds, widthCache) {
  const cached = widthCache.get(nodeId);
  if (cached !== undefined) return cached;

  const childIds = visibleChildIds(index, nodeId, visibleNodeIds);
  let width = NODE_WIDTH;
  if (childIds.length) {
    const childrenWidth =
      childIds.reduce(
        (sum, childId) =>
          sum + measureSubtree(index, childId, visibleNodeIds, widthCache),
        0,
      ) + MIN_HORIZONTAL_GAP * (childIds.length - 1);
    width = Math.max(NODE_WIDTH, childrenWidth);
  }

  widthCache.set(nodeId, width);
  return width;
}

function placeSubtree({
  index,
  nodeId,
  left,
  depth,
  visibleNodeIds,
  widthCache,
  positions,
}) {
  const subtreeWidth = widthCache.get(nodeId);
  positions.set(nodeId, {
    x: left + (subtreeWidth - NODE_WIDTH) / 2,
    y: depth * ROW_HEIGHT,
  });

  const childIds = visibleChildIds(index, nodeId, visibleNodeIds);
  if (!childIds.length) return;

  const childrenWidth =
    childIds.reduce((sum, childId) => sum + widthCache.get(childId), 0) +
    MIN_HORIZONTAL_GAP * (childIds.length - 1);

  let cursor = left + (subtreeWidth - childrenWidth) / 2;
  for (const childId of childIds) {
    placeSubtree({
      index,
      nodeId: childId,
      left: cursor,
      depth: depth + 1,
      visibleNodeIds,
      widthCache,
      positions,
    });
    cursor += widthCache.get(childId) + MIN_HORIZONTAL_GAP;
  }
}

/**
 * @returns {Map<string, {x: number, y: number}>} 仅包含可见节点的坐标
 */
/**
 * 卫星节点不属于树，挂在其锚点节点右侧纵向排列，不影响树的宽度计算。
 */
function placeSatellites(positions, satelliteAnchorById) {
  const countByAnchor = new Map();
  for (const [satelliteId, anchorId] of satelliteAnchorById) {
    const anchorPosition = positions.get(anchorId);
    if (!anchorPosition) continue;
    const slot = countByAnchor.get(anchorId) ?? 0;
    countByAnchor.set(anchorId, slot + 1);
    positions.set(satelliteId, {
      x: anchorPosition.x + NODE_WIDTH + MIN_HORIZONTAL_GAP,
      y: anchorPosition.y + slot * (NODE_HEIGHT + MIN_HORIZONTAL_GAP),
    });
  }
}

export function layoutVisibleGraph({
  index,
  visibleNodeIds,
  depthById,
  satelliteAnchorById = null,
  previousPositions = null,
  anchorNodeId = null,
}) {
  const positions = new Map();
  const widthCache = new Map();

  const rootIds = [...visibleNodeIds].filter(
    (id) => (depthById.get(id) ?? 0) === 0,
  );

  let cursor = 0;
  for (const rootId of rootIds) {
    const width = measureSubtree(index, rootId, visibleNodeIds, widthCache);
    placeSubtree({
      index,
      nodeId: rootId,
      left: cursor,
      depth: 0,
      visibleNodeIds,
      widthCache,
      positions,
    });
    cursor += width + ROOT_GAP;
  }

  if (satelliteAnchorById?.size) {
    placeSatellites(positions, satelliteAnchorById);
  }

  return applyAnchorCompensation(positions, previousPositions, anchorNodeId);
}

/**
 * 整体平移布局结果，使 anchor 节点的画布坐标与上一次一致，
 * 让用户操作的节点在屏幕上保持不动。
 */
export function applyAnchorCompensation(positions, previousPositions, anchorNodeId) {
  if (!anchorNodeId || !previousPositions) return positions;

  const previous = previousPositions.get(anchorNodeId);
  const current = positions.get(anchorNodeId);
  if (!previous || !current) return positions;

  const dx = previous.x - current.x;
  const dy = previous.y - current.y;
  if (dx === 0 && dy === 0) return positions;

  const shifted = new Map();
  for (const [id, position] of positions) {
    shifted.set(id, { x: position.x + dx, y: position.y + dy });
  }
  return shifted;
}
