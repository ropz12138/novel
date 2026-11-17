import { describe, it, expect } from "vitest";
import { buildGraphIndex } from "./canvasGraph";
import { projectVisibleGraph, toggleExpanded } from "./canvasVisibility";
const node = (id, type, sort_order) => ({ id, data: { type, sort_order } });
describe("独立章节可见性", () => {
  it("全部章节可见，历史展开状态不再影响章节显示", () => {
    const index = buildGraphIndex([node("c2", "chapter", 2), node("c1", "chapter", 1),
      node("n", "note", 1), node("old", "plot", 1)], [{ source: "old", target: "c1" }]);
    for (const expandedNodeIds of [new Set(), new Set(["old"])]) {
      const view = projectVisibleGraph({ index, expandedNodeIds, focusNodeId: "c2", defaultExpandDepth: 0 });
      expect([...view.visibleNodeIds]).toEqual(["c1", "c2"]);
      expect(view.visibleEdges).toEqual([]);
      expect([...view.depthById.values()]).toEqual([0, 0]);
    }
  });
  it("空画布和切换集合可正常处理", () => {
    const state = new Set(["a"]);
    expect(toggleExpanded(state, "a").size).toBe(0);
    expect(state.has("a")).toBe(true);
    expect(projectVisibleGraph({ index: buildGraphIndex([], []), expandedNodeIds: state }).visibleNodes).toEqual([]);
  });
});
