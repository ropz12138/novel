import { describe, it, expect } from "vitest";
import { buildGraphIndex, hierarchyRootIds, ancestorChain, descendantIds,
  hasHierarchyChildren, hiddenDescendantSummary } from "./canvasGraph";
const node = (id, type, sort_order) => ({ id, data: { type, sort_order } });
describe("作品章节索引", () => {
  it("章节按 sort_order 排序，资料与旧节点不进入主画布", () => {
    const index = buildGraphIndex([node("b", "chapter", 2), node("z", "chapter", 1), node("a", "chapter", 2),
      node("n", "note", 1), node("old", "outline", 1)], [{ source: "old", target: "z" }, { source: "z", target: "b" }]);
    expect(hierarchyRootIds(index)).toEqual(["z", "a", "b"]);
    expect(index.parentById.size).toBe(0);
    expect(ancestorChain(index, "b")).toEqual([]);
    expect(descendantIds(index, "z")).toEqual([]);
    expect(hasHierarchyChildren(index, "z")).toBe(false);
    expect(hiddenDescendantSummary(index, "z", new Set())).toEqual({ total: 0, byType: {}, text: "" });
  });
});
