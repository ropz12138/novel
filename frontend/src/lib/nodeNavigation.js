import { compareSiblings } from "./canvasOrder";
import { HIERARCHY_CHAIN } from "./canvasRelation";

const NAVIGATION_GROUPS = [...HIERARCHY_CHAIN, "character", "worldbuilding", "note", "reviewer_note"];

export function firstChapterNode(nodes) {
  return orderedNavigationNodes(nodes).find((node) => node.type === "chapter") ?? null;
}

export function orderedNavigationNodes(nodes) {
  return NAVIGATION_GROUPS.flatMap((type) => nodes
    .filter((node) => node.data?.type === type)
    .sort(compareSiblings)
    .map((node) => ({ id: node.id, ...node.data })));
}
