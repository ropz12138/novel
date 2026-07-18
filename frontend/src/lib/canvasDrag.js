/** Ctrl + 拖拽框选（marquee）修饰键，与 React Flow selectionKeyCode 一致。 */
export const CANVAS_MARQUEE_KEY_CODE = "Control";

/** 选中变化时是否应关闭详情抽屉（拖拽过程中忽略）。 */
export function shouldClearDrawerOnSelection(selectedCount, isDragging) {
  if (isDragging) return false;
  return selectedCount === 0 || selectedCount > 1;
}


/** 对比拖拽前 snapshot，返回位置发生变化的节点。 */
export function getMovedNodesFromSnapshot(snapshot, currentNodes) {
  if (!snapshot?.nodes?.length || !currentNodes?.length) return [];
  const before = new Map(
    snapshot.nodes.map((n) => [n.id, { x: n.position_x, y: n.position_y }]),
  );
  return currentNodes.filter((node) => {
    const prev = before.get(node.id);
    if (!prev) return false;
    return prev.x !== node.position.x || prev.y !== node.position.y;
  });
}

/** 将 moved 节点转为 updateNode API 载荷。 */
export function toNodePositionUpdates(nodes) {
  return (nodes || []).map((node) => ({
    id: node.id,
    position_x: node.position.x,
    position_y: node.position.y,
  }));
}

/** 批量持久化节点坐标。 */
export async function persistNodePositionUpdates(movedNodes, updateNodeFn) {
  const updates = toNodePositionUpdates(movedNodes);
  await Promise.all(
    updates.map(({ id, position_x, position_y }) =>
      updateNodeFn(id, { position_x, position_y }),
    ),
  );
}
