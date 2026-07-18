/** 是否应忽略画布快捷键（输入框、可编辑区域等）。 */
export function shouldIgnoreCanvasKeyEvent(event) {
  const target = event.target;
  if (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  ) {
    return true;
  }
  return false;
}

/** Delete / Backspace 删除选中节点（不含组合键）。 */
export function isCanvasDeleteKey(event) {
  if (event.ctrlKey || event.metaKey || event.altKey) return false;
  return event.key === "Delete" || event.key === "Backspace";
}

/** 当前可删除的选中节点 id（跳过折叠隐藏节点）。 */
export function getDeletableSelectedNodeIds(nodes) {
  return (nodes || [])
    .filter((n) => n.selected && !n.hidden)
    .map((n) => n.id)
    .filter(Boolean);
}

/** 从本地图状态移除节点及其关联边/角色关系。 */
export function filterGraphAfterNodeRemoval(nodeIds, nodes, edges, characterRelations = []) {
  const idSet = new Set(nodeIds || []);
  return {
    nodes: (nodes || []).filter((n) => !idSet.has(n.id)),
    edges: (edges || []).filter((e) => !idSet.has(e.source) && !idSet.has(e.target)),
    characterRelations: (characterRelations || []).filter(
      (r) => !idSet.has(r.source) && !idSet.has(r.target),
    ),
  };
}
