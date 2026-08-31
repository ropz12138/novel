/**
 * 画布视图状态（展开集合与 viewport）的本地持久化。
 *
 * 视图状态只影响观看方式，不属于作品数据，因此存在 localStorage 而非后端。
 * 记录带版本号：布局规则或字段含义变化后，旧记录恢复出来的画面可能与新规则
 * 冲突，此时整条丢弃比迁移更可靠。
 */

export const VIEW_STATE_VERSION = 1;

const KEY_PREFIX = "novel:canvas-view:v";

/** 安全获取 localStorage：SSR 与隐私模式下访问本身就会抛错。 */
export function localViewStorage() {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function viewStateStorageKey(workId) {
  return `${KEY_PREFIX}${VIEW_STATE_VERSION}:${workId}`;
}

function isValidViewport(viewport) {
  if (!viewport || typeof viewport !== "object") return false;
  return ["x", "y", "zoom"].every(
    (field) => typeof viewport[field] === "number" && Number.isFinite(viewport[field]),
  );
}

export function loadViewState(workId, storage) {
  if (!workId || !storage) return null;

  let raw;
  try {
    raw = storage.getItem(viewStateStorageKey(workId));
  } catch {
    return null;
  }
  if (!raw) return null;

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (parsed?.version !== VIEW_STATE_VERSION) return null;

  const ids = Array.isArray(parsed.expanded_node_ids) ? parsed.expanded_node_ids : [];
  return {
    expandedNodeIds: new Set(ids.filter((id) => typeof id === "string")),
    viewport: isValidViewport(parsed.viewport) ? parsed.viewport : null,
  };
}

export function saveViewState(workId, { expandedNodeIds, viewport }, storage) {
  if (!workId || !storage) return;

  const payload = {
    version: VIEW_STATE_VERSION,
    expanded_node_ids: [...(expandedNodeIds ?? [])],
    viewport: isValidViewport(viewport) ? viewport : null,
  };
  try {
    storage.setItem(viewStateStorageKey(workId), JSON.stringify(payload));
  } catch {
    // 隐私模式或配额耗尽：视图状态丢失不影响画布可用性
  }
}

export function clearViewState(workId, storage) {
  if (!workId || !storage) return;
  try {
    storage.removeItem(viewStateStorageKey(workId));
  } catch {
    // 同上
  }
}

/** 剔除已被删除的节点，避免记录随编辑无限增长。 */
export function pruneExpandedIds(expandedNodeIds, existingNodeIds) {
  const pruned = new Set();
  for (const id of expandedNodeIds ?? []) {
    if (existingNodeIds?.has(id)) pruned.add(id);
  }
  return pruned;
}
