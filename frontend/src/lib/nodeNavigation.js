import { compareSiblings } from "./canvasOrder";
import { HIERARCHY_CHAIN } from "./canvasRelation";

const NAVIGATION_GROUPS = [...HIERARCHY_CHAIN, "character", "worldbuilding", "note"];

export function firstOutlineNode(nodes) {
  return orderedNavigationNodes(nodes).find((node) => node.type === "outline") ?? null;
}

export function orderedNavigationNodes(nodes) {
  return NAVIGATION_GROUPS.flatMap((type) => nodes
    .filter((node) => node.data?.type === type)
    .sort(compareSiblings)
    .map((node) => ({ id: node.id, ...node.data })));
}
