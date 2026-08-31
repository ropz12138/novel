import { describe, it, expect } from "vitest";
import {
  buildGraphIndex,
  hierarchyRootIds,
  ancestorChain,
  descendantIds,
  hiddenDescendantSummary,
  hasHierarchyChildren,
} from "./canvasGraph";

/**
 * 测试用图：
 *   o1 (outline)
 *     ├─ v1 (volume)
 *     │    ├─ p1 (plot) ── c1, c2 (chapter)
 *     │    └─ p2 (plot) ── c3
 *     └─ v2 (volume)
 *   孤立：w1 (worldbuilding/global), n1 (note/global), hero (character/global)
 *   关联：npc (character/minor) ── reference → c1
 *   顺序：c1 → c2 为 sequence
 */
const nodes = [
  { id: "o1", data: { type: "outline", label: "大纲", scope: "local" } },
  { id: "v1", data: { type: "volume", label: "第一卷", scope: "local" } },
  { id: "v2", data: { type: "volume", label: "第二卷", scope: "local" } },
  { id: "p1", data: { type: "plot", label: "情节一", scope: "local" } },
  { id: "p2", data: { type: "plot", label: "情节二", scope: "local" } },
  { id: "c1", data: { type: "chapter", label: "第1章", scope: "local" } },
  { id: "c2", data: { type: "chapter", label: "第2章", scope: "local" } },
  { id: "c3", data: { type: "chapter", label: "第3章", scope: "local" } },
  { id: "w1", data: { type: "worldbuilding", label: "世界观", scope: "global" } },
  { id: "n1", data: { type: "note", label: "笔记", scope: "global" } },
  { id: "hero", data: { type: "character", label: "主角", scope: "global" } },
  { id: "npc", data: { type: "character", label: "配角", scope: "minor" } },
];

const edge = (source, target, edgeType = "包含") => ({
  id: `${source}->${target}`,
  source,
  target,
  data: { edge_type: edgeType },
});

const edges = [
  edge("o1", "v1"),
  edge("o1", "v2"),
  edge("v1", "p1"),
  edge("v1", "p2"),
  edge("p1", "c1"),
  edge("p1", "c2"),
  edge("p2", "c3"),
  edge("c1", "c2", "接续"),
  edge("npc", "c1", "登场"),
];

describe("buildGraphIndex", () => {
  it("父子索引只包含 hierarchy 边", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(index.parentById.get("v1")).toBe("o1");
    expect(index.parentById.get("p1")).toBe("v1");
    expect(index.parentById.get("c1")).toBe("p1");
  });

  it("sequence 边不产生父子关系", () => {
    const index = buildGraphIndex(nodes, edges);
    // c1 → c2 是 sequence，c2 的父节点仍是 p1
    expect(index.parentById.get("c2")).toBe("p1");
  });

  it("reference 边不产生父子关系", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(index.parentById.get("c1")).not.toBe("npc");
  });

  it("子节点列表按同级顺序排列", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(index.childIdsById.get("p1")).toEqual(["c1", "c2"]);
    expect(index.childIdsById.get("v1")).toEqual(["p1", "p2"]);
  });

  it("没有子节点的节点返回空列表", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(index.childIdsById.get("c3") ?? []).toEqual([]);
  });
});

describe("hierarchyRootIds", () => {
  it("只返回没有 hierarchy 父边的层级链节点", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(hierarchyRootIds(index)).toEqual(["o1"]);
  });

  it("孤立节点不算结构根节点", () => {
    const index = buildGraphIndex(nodes, edges);
    const roots = hierarchyRootIds(index);
    expect(roots).not.toContain("w1");
    expect(roots).not.toContain("n1");
    expect(roots).not.toContain("hero");
  });

  it("有关联边的配角不算结构根节点", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(hierarchyRootIds(index)).not.toContain("npc");
  });

  it("多个游离层级链节点构成森林", () => {
    const forestNodes = [
      { id: "o1", data: { type: "outline", label: "甲", scope: "local" } },
      { id: "o2", data: { type: "outline", label: "乙", scope: "local" } },
      { id: "v1", data: { type: "volume", label: "卷", scope: "local" } },
    ];
    const index = buildGraphIndex(forestNodes, [edge("o1", "v1")]);
    expect(hierarchyRootIds(index)).toEqual(["o1", "o2"]);
  });
});

describe("ancestorChain", () => {
  it("返回从直接父节点到根的链", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(ancestorChain(index, "c1")).toEqual(["p1", "v1", "o1"]);
  });

  it("根节点没有祖先", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(ancestorChain(index, "o1")).toEqual([]);
  });

  it("未知节点返回空链", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(ancestorChain(index, "missing")).toEqual([]);
  });
});

describe("descendantIds", () => {
  it("返回全部后代", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(new Set(descendantIds(index, "v1"))).toEqual(
      new Set(["p1", "p2", "c1", "c2", "c3"]),
    );
  });

  it("叶子节点没有后代", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(descendantIds(index, "c1")).toEqual([]);
  });
});

describe("hasHierarchyChildren", () => {
  it("有结构子节点时为真", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(hasHierarchyChildren(index, "v1")).toBe(true);
  });

  it("只有 sequence 或 reference 邻居时为假", () => {
    const index = buildGraphIndex(nodes, edges);
    // c1 只有 sequence 出边 c1→c2 与 reference 入边 npc→c1
    expect(hasHierarchyChildren(index, "c1")).toBe(false);
  });
});

describe("hiddenDescendantSummary", () => {
  it("统计不在可见集合中的后代总数与类型分布", () => {
    const index = buildGraphIndex(nodes, edges);
    // v1 的子节点 p1/p2 可见，但章节尚未展开
    const visible = new Set(["o1", "v1", "v2", "p1", "p2"]);
    const summary = hiddenDescendantSummary(index, "v1", visible);
    expect(summary.total).toBe(3);
    expect(summary.byType).toEqual({ chapter: 3 });
  });

  it("节点未展开时全部后代都算隐藏", () => {
    const index = buildGraphIndex(nodes, edges);
    const visible = new Set(["o1", "v1", "v2"]);
    const summary = hiddenDescendantSummary(index, "v1", visible);
    expect(summary.total).toBe(5);
    expect(summary.byType).toEqual({ plot: 2, chapter: 3 });
  });

  it("后代全部可见时总数为 0", () => {
    const index = buildGraphIndex(nodes, edges);
    const visible = new Set(["o1", "v1", "v2", "p1", "p2", "c1", "c2", "c3"]);
    expect(hiddenDescendantSummary(index, "v1", visible).total).toBe(0);
  });

  it("生成可读摘要文本", () => {
    const index = buildGraphIndex(nodes, edges);
    const summary = hiddenDescendantSummary(index, "v1", new Set(["o1", "v1", "v2"]));
    expect(summary.text).toBe("2 个情节 · 3 章");
  });

  it("默认深度下根节点的直接子节点不计入隐藏", () => {
    const index = buildGraphIndex(nodes, edges);
    // o1 的子节点 v1/v2 因默认展开深度可见，即便它们不在 expandedNodeIds 中
    const visible = new Set(["o1", "v1", "v2"]);
    const summary = hiddenDescendantSummary(index, "o1", visible);
    expect(summary.byType.volume).toBeUndefined();
    expect(summary.total).toBe(5);
  });
});
