/**
 * 关系类别派生 —— 与 backend/services/edge_relation.py 保持一致。
 *
 * 关系类别不存储在边上，而是从两端节点类型推导。判据必须是"严格降一级"：
 * chapter → chapter 的边两端都属于层级链类型，若只判断"两端是否都在层级链内"，
 * 前一章会被当成后一章的父节点，导致树深度错乱。
 */

export const RELATION_HIERARCHY = "hierarchy";
export const RELATION_SEQUENCE = "sequence";
export const RELATION_REFERENCE = "reference";

export const HIERARCHY_CHAIN = ["outline", "volume", "plot", "chapter"];

const LEVELS = new Map(HIERARCHY_CHAIN.map((type, level) => [type, level]));

export function hierarchyLevel(nodeType) {
  const level = LEVELS.get((nodeType || "").trim());
  return level === undefined ? null : level;
}

/** 返回关系类别；null 表示该组合非法（跨级或反向）。 */
export function deriveRelationKind(sourceType, targetType) {
  const sourceLevel = hierarchyLevel(sourceType);
  const targetLevel = hierarchyLevel(targetType);

  if (sourceLevel === null || targetLevel === null) return RELATION_REFERENCE;
  if (targetLevel === sourceLevel) return RELATION_SEQUENCE;
  if (targetLevel === sourceLevel + 1) return RELATION_HIERARCHY;
  return null;
}

export function nodeTypeById(nodes) {
  return new Map(nodes.map((n) => [n.id, n.data?.type]));
}

export function edgeRelationKind(edge, typeById) {
  const sourceType = typeById.get(edge.source);
  const targetType = typeById.get(edge.target);
  if (!sourceType || !targetType) return null;
  return deriveRelationKind(sourceType, targetType);
}

export function isHierarchyEdge(edge, typeById) {
  return edgeRelationKind(edge, typeById) === RELATION_HIERARCHY;
}

/** 参与画布树布局的节点类型。 */
export function isCanvasStructuralType(nodeType) {
  return hierarchyLevel(nodeType) !== null;
}

/**
 * 孤立节点：后端规定 scope=global 的节点禁止任何连线
 * （worldbuilding、note 以及主角 character），它们在图中没有任何边。
 * 这类节点默认不进入画布，否则会以"根节点"身份铺满画布。
 */
export function isIsolatedType(nodeType, scope) {
  if (isCanvasStructuralType(nodeType)) return false;
  return scope === "global";
}

export function isIsolatedNode(node) {
  return isIsolatedType(node?.data?.type, node?.data?.scope);
}
