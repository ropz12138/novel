import { describe, it, expect } from "vitest";
import { buildGraphIndex } from "./canvasGraph";
import { projectVisibleGraph } from "./canvasVisibility";
import {
  MIN_HORIZONTAL_GAP,
  MIN_VERTICAL_GAP,
  ROOT_GAP,
  layoutVisibleGraph,
} from "./canvasLayout";
import { NODE_WIDTH, NODE_HEIGHT } from "./nodeDimensions";

const node = (id, type, label) => ({
  id,
  data: { type, label, scope: "local" },
});

const edge = (source, target, edgeType = "包含") => ({
  id: `${source}->${target}`,
  source,
  target,
  data: { edge_type: edgeType },
});

const nodes = [
  node("o1", "outline", "大纲"),
  node("v1", "volume", "第一卷"),
  node("v2", "volume", "第二卷"),
  node("p1", "plot", "情节一"),
  node("p2", "plot", "情节二"),
  node("c1", "chapter", "第1章"),
  node("c2", "chapter", "第2章"),
  node("c3", "chapter", "第3章"),
];

const edges = [
  edge("o1", "v1"),
  edge("o1", "v2"),
  edge("v1", "p1"),
  edge("v1", "p2"),
  edge("p1", "c1"),
  edge("p1", "c2"),
  edge("p2", "c3"),
];

const layoutWith = (expandedIds = [], options = {}) => {
  const index = buildGraphIndex(nodes, edges);
  const visible = projectVisibleGraph({
    index,
    expandedNodeIds: new Set(expandedIds),
  });
  return layoutVisibleGraph({
    index,
    visibleNodeIds: visible.visibleNodeIds,
    depthById: visible.depthById,
    ...options,
  });
};

const boundsOf = (positions, id) => {
  const p = positions.get(id);
  return {
    left: p.x,
    right: p.x + NODE_WIDTH,
    top: p.y,
    bottom: p.y + NODE_HEIGHT,
  };
};

const overlaps = (a, b) =>
  a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

describe("间距常量", () => {
  it("最小间距是明确取值而非模糊约定", () => {
    expect(MIN_HORIZONTAL_GAP).toBeGreaterThan(0);
    expect(MIN_VERTICAL_GAP).toBeGreaterThan(0);
    expect(ROOT_GAP).toBeGreaterThanOrEqual(MIN_HORIZONTAL_GAP);
  });
});

describe("树布局", () => {
  it("深度决定 Y 坐标", () => {
    const positions = layoutWith(["v1"]);
    const y0 = positions.get("o1").y;
    const y1 = positions.get("v1").y;
    const y2 = positions.get("p1").y;
    expect(y1).toBeGreaterThan(y0);
    expect(y2).toBeGreaterThan(y1);
    expect(y1 - y0).toBe(NODE_HEIGHT + MIN_VERTICAL_GAP);
    expect(y2 - y1).toBe(NODE_HEIGHT + MIN_VERTICAL_GAP);
  });

  it("同一深度的节点 Y 坐标相同", () => {
    const positions = layoutWith();
    expect(positions.get("v1").y).toBe(positions.get("v2").y);
  });

  it("父节点水平居中于其可见子节点", () => {
    const positions = layoutWith();
    const parentCenter = positions.get("o1").x + NODE_WIDTH / 2;
    const left = positions.get("v1").x + NODE_WIDTH / 2;
    const right = positions.get("v2").x + NODE_WIDTH / 2;
    expect(parentCenter).toBeCloseTo((left + right) / 2, 5);
  });

  it("只有一个子节点时父子对齐", () => {
    const positions = layoutWith(["v1", "p2"]);
    expect(positions.get("p2").x).toBeCloseTo(positions.get("c3").x, 5);
  });

  it("兄弟节点按同级顺序从左到右排列", () => {
    const positions = layoutWith(["v1", "p1"]);
    expect(positions.get("c1").x).toBeLessThan(positions.get("c2").x);
    expect(positions.get("p1").x).toBeLessThan(positions.get("p2").x);
  });

  it("同层相邻节点间距不小于最小水平间距", () => {
    const positions = layoutWith(["v1", "p1", "p2"]);
    const byDepth = new Map();
    for (const [id, p] of positions) {
      if (!byDepth.has(p.y)) byDepth.set(p.y, []);
      byDepth.get(p.y).push(p.x);
    }
    for (const xs of byDepth.values()) {
      xs.sort((a, b) => a - b);
      for (let i = 1; i < xs.length; i += 1) {
        expect(xs[i] - (xs[i - 1] + NODE_WIDTH)).toBeGreaterThanOrEqual(
          MIN_HORIZONTAL_GAP,
        );
      }
    }
  });

  it("任意两个可见节点的包围盒都不重叠", () => {
    const positions = layoutWith(["v1", "p1", "p2"]);
    const ids = [...positions.keys()];
    for (let i = 0; i < ids.length; i += 1) {
      for (let j = i + 1; j < ids.length; j += 1) {
        expect(
          overlaps(boundsOf(positions, ids[i]), boundsOf(positions, ids[j])),
        ).toBe(false);
      }
    }
  });

  it("只对可见节点计算坐标", () => {
    const positions = layoutWith();
    expect(positions.has("o1")).toBe(true);
    expect(positions.has("v1")).toBe(true);
    expect(positions.has("p1")).toBe(false);
    expect(positions.has("c1")).toBe(false);
  });

  it("收起后不留下隐藏节点造成的空洞", () => {
    const expandedWide = layoutWith(["v1", "p1", "p2"]);
    const collapsed = layoutWith();
    const widthOf = (positions) => {
      const xs = [...positions.values()].map((p) => p.x);
      return Math.max(...xs) - Math.min(...xs);
    };
    expect(widthOf(collapsed)).toBeLessThan(widthOf(expandedWide));
  });
});

describe("森林", () => {
  const forestNodes = [
    node("o1", "outline", "甲"),
    node("o2", "outline", "乙"),
    node("v1", "volume", "卷一"),
  ];
  const forestEdges = [edge("o1", "v1")];

  it("多个根节点横向排列且保留额外间距", () => {
    const index = buildGraphIndex(forestNodes, forestEdges);
    const visible = projectVisibleGraph({ index, expandedNodeIds: new Set() });
    const positions = layoutVisibleGraph({
      index,
      visibleNodeIds: visible.visibleNodeIds,
      depthById: visible.depthById,
    });
    const first = positions.get("o1");
    const second = positions.get("o2");
    expect(second.x).toBeGreaterThan(first.x);
    expect(second.y).toBe(first.y);
  });
});

describe("anchor 补偿", () => {
  it("被操作节点的画布坐标保持不变", () => {
    const before = layoutWith();
    const previousPositions = new Map(before);
    const after = layoutWith(["v1"], {
      previousPositions,
      anchorNodeId: "v1",
    });
    expect(after.get("v1").x).toBeCloseTo(previousPositions.get("v1").x, 5);
    expect(after.get("v1").y).toBeCloseTo(previousPositions.get("v1").y, 5);
  });

  it("补偿是整体平移，不改变节点相对关系", () => {
    const before = layoutWith();
    const previousPositions = new Map(before);
    const plain = layoutWith(["v1"]);
    const shifted = layoutWith(["v1"], {
      previousPositions,
      anchorNodeId: "v1",
    });
    const dx = shifted.get("v1").x - plain.get("v1").x;
    const dy = shifted.get("v1").y - plain.get("v1").y;
    for (const id of plain.keys()) {
      expect(shifted.get(id).x - plain.get(id).x).toBeCloseTo(dx, 5);
      expect(shifted.get(id).y - plain.get(id).y).toBeCloseTo(dy, 5);
    }
  });

  it("anchor 不在上一次布局中时不做补偿", () => {
    const plain = layoutWith(["v1"]);
    const withAnchor = layoutWith(["v1"], {
      previousPositions: new Map(),
      anchorNodeId: "v1",
    });
    expect(withAnchor.get("v1").x).toBeCloseTo(plain.get("v1").x, 5);
  });

  it("未指定 anchor 时结果与无补偿一致", () => {
    const plain = layoutWith(["v1"]);
    const noAnchor = layoutWith(["v1"], { previousPositions: new Map(plain) });
    expect(noAnchor.get("o1").x).toBeCloseTo(plain.get("o1").x, 5);
  });
});

describe("确定性", () => {
  it("相同输入重复计算结果一致", () => {
    const first = layoutWith(["v1", "p1"]);
    const second = layoutWith(["v1", "p1"]);
    for (const [id, p] of first) {
      expect(second.get(id)).toEqual(p);
    }
  });
});

describe("空图", () => {
  it("没有可见节点时返回空结果", () => {
    const index = buildGraphIndex([], []);
    const positions = layoutVisibleGraph({
      index,
      visibleNodeIds: new Set(),
      depthById: new Map(),
    });
    expect(positions.size).toBe(0);
  });
});
