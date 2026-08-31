/**
 * 同级顺序排序键 —— 对应 backend/services/chapter_history_service.chapter_order_key。
 *
 * 不引入 sort_order 字段：现有数据已经能提供确定性顺序。回退链依次为
 * extra_data 显式序号 → 标题中的章号 → layer → x 坐标 → 创建时间 → id。
 *
 * 已知副作用：Agent 不再写坐标后，x 坐标一档会退化为常量，顺序由创建时间决定。
 * 结果依然确定。等到需要支持用户手动拖拽调整同级顺序时，再引入独立字段。
 */

const EXPLICIT_ORDER_FIELDS = ["chapter_number", "chapter_index", "order", "sequence"];

const CHAPTER_TITLE_PATTERN = /第\s*(\d+)\s*章/;

function explicitOrder(extraData) {
  for (const field of EXPLICIT_ORDER_FIELDS) {
    const value = extraData?.[field];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && /^\d+$/.test(value.trim())) {
      return Number(value.trim());
    }
  }
  return null;
}

function titleOrder(title) {
  const match = CHAPTER_TITLE_PATTERN.exec(title || "");
  return match ? Number(match[1]) : null;
}

function createdAtMillis(data) {
  const raw = data?.created_at;
  if (!raw) return 0;
  const parsed = Date.parse(raw);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * 返回定长排序键 [bucket, primary, layer, x, createdAt, id]。
 * bucket 0 表示存在明确编号，排在 bucket 1 之前。
 */
export function siblingOrderKey(node) {
  const data = node?.data || {};
  const numbered = explicitOrder(data.extra_data) ?? titleOrder(data.label);
  return [
    numbered === null ? 1 : 0,
    numbered === null ? 0 : numbered,
    data.layer ?? 0,
    node?.position?.x ?? 0,
    createdAtMillis(data),
    node?.id ?? "",
  ];
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
