/**
 * 同级顺序排序键 —— 对应 backend/services/chapter_history_service.chapter_order_key。
 *
 * 顺序只认 sort_order：它在创建节点时必填。此前从 extra_data 序号、标题章号与
 * 坐标逐级推断，同一份顺序因此有多个来源，彼此可能矛盾；Agent 不再写坐标后
 * 顺序还会退化到创建时间，而批量创建的时间戳可能相同。
 *
 * id 只作为并列时的 tie-breaker，保证两次排序结果一致。
 */

export function siblingOrderKey(node) {
  const data = node?.data || {};
  return [data.sort_order ?? 0, node?.id ?? ""];
}

export function compareSiblings(a, b) {
  const keyA = siblingOrderKey(a);
  const keyB = siblingOrderKey(b);
  for (let i = 0; i < keyA.length; i += 1) {
    const left = keyA[i];
    const right = keyB[i];
    if (left === right) continue;
    if (typeof left === "number" && typeof right === "number") {
      return left - right;
    }
    return String(left) < String(right) ? -1 : 1;
  }
  return 0;
}

export function sortSiblings(nodes) {
  return [...nodes].sort(compareSiblings);
}

/**
 * 用户手动新增节点时的 sort_order：排在同类型节点末尾。
 *
 * 手动新增的节点此刻还没有父连线，无法按"同父下最大值 + 1"计算，
 * 因此以类型为范围取最大值递增。
 */
export function nextSortOrder(nodes, nodeType) {
  let max = 0;
  for (const node of nodes ?? []) {
    if (node?.data?.type !== nodeType) continue;
    const value = node.data.sort_order;
    if (typeof value === "number" && Number.isFinite(value) && value > max) {
      max = value;
    }
  }
  return max + 1;
}
