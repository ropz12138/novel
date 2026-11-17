import { describe, expect, it } from "vitest";
import { orderedNavigationNodes } from "./nodeNavigation";
import { isCanvasStructuralType, isIsolatedType } from "./canvasRelation";
import { buildGraphIndex } from "./canvasGraph";
import { projectVisibleGraph } from "./canvasVisibility";

const node = (id, type, sort_order) => ({ id, data: { type, sort_order } });

describe("独立章节", () => {
  it("导航移除三类结构节点，章节按顺序排列", () => {
    const nodes = [node("o", "outline", 1), node("v", "volume", 1), node("p", "plot", 1),
      node("c2", "chapter", 2), node("c1", "chapter", 1), node("n", "note", 1)];
    expect(orderedNavigationNodes(nodes).map(n => n.id)).toEqual(["c1", "c2", "n"]);
    for (const type of ["outline", "volume", "plot"]) {
      expect(isCanvasStructuralType(type)).toBe(false);
      expect(isIsolatedType(type)).toBe(false);
    }
  });

  it("无父节点的章节全部显示在画布上", () => {
    const nodes = [node("c2", "chapter", 2), node("c1", "chapter", 1), node("n", "note", 1)];
    const view = projectVisibleGraph({ index: buildGraphIndex(nodes, []), expandedNodeIds: new Set() });
    expect([...view.visibleNodeIds]).toEqual(["c1", "c2"]);
    expect(view.visibleEdges).toEqual([]);
  });
});
