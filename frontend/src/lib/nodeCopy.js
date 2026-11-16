/**
 * 跨作品复制前，根据当前画布算出要带走的下级和角色。
 * 父子关系与 backend/services/edge_relation.py 一致：只沿严格降一级的边向下。
 */
import { buildGraphIndex, descendantIds } from "./canvasGraph";

export function describeNodeCopy(nodes, edges, nodeId) {
  const index = buildGraphIndex(nodes, edges);
  const node = index.nodeById.get(nodeId);
  if (!node) return null;

  const copiedIds = [nodeId, ...descendantIds(index, nodeId)];
  const seen = new Set();
  let characterCount = 0;
  let omittedCount = 0;
  for (const id of copiedIds) {
    const characters = index.nodeById.get(id)?.data?.extra_data?.characters;
    if (!Array.isArray(characters)) continue;
    for (const item of characters) {
      if (!item || typeof item !== "object" || !item.id || seen.has(item.id)) continue;
      seen.add(item.id);
      const character = index.nodeById.get(item.id);
      if (character?.data?.type === "character") characterCount += 1;
      else omittedCount += 1;
    }
  }

  return {
    rootId: nodeId,
    title: node.data?.label || "",
    descendantCount: copiedIds.length - 1,
    characterCount,
    omittedCount,
  };
}

export function copyDialogText(description) {
  if (!description) {
    return "将此节点复制到所选作品，并作为独立结构放在那里。";
  }
  const extras = [];
  if (description.descendantCount) extras.push(`下级 ${description.descendantCount} 个节点`);
  if (description.characterCount) extras.push(`章节引用的 ${description.characterCount} 个角色`);
  const verb = extras.length ? `会连同${extras.join("、")}，一起` : "会";
  const omitted = description.omittedCount
    ? `有 ${description.omittedCount} 条已失效的角色引用不会带过去。`
    : "";
  return `「${description.title}」${verb}复制到所选作品，并作为独立结构放在那里。${omitted}`;
}
