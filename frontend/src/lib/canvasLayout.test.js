import { describe, it, expect } from "vitest";
import { buildGraphIndex } from "./canvasGraph";
import { projectVisibleGraph } from "./canvasVisibility";
import { layoutVisibleGraph, ROOT_GAP } from "./canvasLayout";
import { NODE_WIDTH } from "./nodeDimensions";
function layout(options = {}) {
  const index = buildGraphIndex([3, 1, 2].map(i => ({ id: `c${i}`, data: { type: "chapter", sort_order: i } })), []);
  const view = projectVisibleGraph({ index, expandedNodeIds: new Set() });
  return layoutVisibleGraph({ index, ...view, ...options });
}
describe("独立章节布局", () => {
  it("按章节顺序横向排列，间距足够且全部位于同一行", () => {
    const positions = layout();
    expect([...positions.keys()]).toEqual(["c1", "c2", "c3"]);
    for (let i = 1; i < 3; i++) {
      expect(positions.get(`c${i + 1}`).x - positions.get(`c${i}`).x).toBe(NODE_WIDTH + ROOT_GAP);
      expect(positions.get(`c${i}`).y).toBe(0);
    }
  });
  it("锚定章节保持原坐标，同时平移其他章节", () => {
    const plain = layout();
    const shifted = layout({ anchorNodeId: "c2", previousPositions: new Map([["c2", { x: 100, y: 200 }]]) });
    expect(shifted.get("c2")).toEqual({ x: 100, y: 200 });
    expect(shifted.get("c3").x - shifted.get("c1").x).toBe(plain.get("c3").x - plain.get("c1").x);
  });
  it("缺少锚点历史时保持自动布局", () => {
    expect(layout({ anchorNodeId: "missing", previousPositions: new Map() })).toEqual(layout());
  });
});
