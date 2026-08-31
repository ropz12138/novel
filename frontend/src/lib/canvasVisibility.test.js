import { describe, it, expect } from "vitest";
import { buildGraphIndex } from "./canvasGraph";
import {
  DEFAULT_EXPAND_DEPTH,
  projectVisibleGraph,
  isNodeExpandable,
  toggleExpanded,
} from "./canvasVisibility";

/**
 *   o1 (outline)
 *     ├─ v1 (volume)
 *     │    ├─ p1 (plot) ── c1, c2 (chapter)
 *     │    └─ p2 (plot) ── c3
 *     └─ v2 (volume)
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

const project = (options = {}) => {
  const index = buildGraphIndex(nodes, edges);
  return projectVisibleGraph({ index, expandedNodeIds: new Set(), ...options });
};

const idsOf = (result) => result.visibleNodes.map((n) => n.id);

describe("默认可见范围", () => {
  it("默认展开深度为 1", () => {
    expect(DEFAULT_EXPAND_DEPTH).toBe(1);
  });

  it("默认只显示根节点与第一层子节点", () => {
    expect(new Set(idsOf(project()))).toEqual(new Set(["o1", "v1", "v2"]));
  });

  it("默认不显示更深层节点", () => {
    const visible = new Set(idsOf(project()));
    expect(visible.has("p1")).toBe(false);
    expect(visible.has("c1")).toBe(false);
  });

  it("孤立节点不进入画布", () => {
    const visible = new Set(idsOf(project()));
    expect(visible.has("w1")).toBe(false);
    expect(visible.has("n1")).toBe(false);
    expect(visible.has("hero")).toBe(false);
  });

  it("关联角色默认也不占用画布", () => {
    expect(new Set(idsOf(project())).has("npc")).toBe(false);
  });

  it("记录每个可见节点的深度", () => {
    const result = project();
    expect(result.depthById.get("o1")).toBe(0);
    expect(result.depthById.get("v1")).toBe(1);
  });
});

describe("展开", () => {
  it("展开节点只显示直接子节点，不递归", () => {
    const visible = new Set(idsOf(project({ expandedNodeIds: new Set(["v1"]) })));
    expect(visible.has("p1")).toBe(true);
    expect(visible.has("p2")).toBe(true);
    expect(visible.has("c1")).toBe(false);
  });

  it("逐层展开两级后章节才出现", () => {
    const visible = new Set(
      idsOf(project({ expandedNodeIds: new Set(["v1", "p1"]) })),
    );
    expect(visible.has("c1")).toBe(true);
    expect(visible.has("c2")).toBe(true);
    expect(visible.has("c3")).toBe(false);
  });

  it("展开状态记录在未展开祖先下时不生效", () => {
    // p1 标记为展开，但父节点 v1 未展开，p1 本身不可见，其子节点也不可见
    const visible = new Set(idsOf(project({ expandedNodeIds: new Set(["p1"]) })));
    expect(visible.has("p1")).toBe(false);
    expect(visible.has("c1")).toBe(false);
  });

  it("收起父节点后后代全部消失，但展开状态保留", () => {
    const expanded = new Set(["v1", "p1"]);
    expect(new Set(idsOf(project({ expandedNodeIds: expanded }))).has("c1")).toBe(
      true,
    );
    expanded.delete("v1");
    const visible = new Set(idsOf(project({ expandedNodeIds: expanded })));
    expect(visible.has("p1")).toBe(false);
    expect(visible.has("c1")).toBe(false);
    // p1 的展开状态仍在集合中，重新展开 v1 时可恢复
    expect(expanded.has("p1")).toBe(true);
    expanded.add("v1");
    expect(new Set(idsOf(project({ expandedNodeIds: expanded }))).has("c1")).toBe(
      true,
    );
  });
});

describe("聚焦与搜索", () => {
  it("聚焦节点自动可见并带上完整祖先链", () => {
    const visible = new Set(idsOf(project({ focusNodeId: "c3" })));
    expect(visible.has("c3")).toBe(true);
    expect(visible.has("p2")).toBe(true);
    expect(visible.has("v1")).toBe(true);
    expect(visible.has("o1")).toBe(true);
  });

  it("聚焦不会顺带展开无关分支", () => {
    const visible = new Set(idsOf(project({ focusNodeId: "c3" })));
    expect(visible.has("c1")).toBe(false);
    expect(visible.has("p1")).toBe(true); // p1 是 v1 的直接子节点，v1 被展开后可见
  });

  it("聚焦孤立节点不会把它塞进画布", () => {
    expect(new Set(idsOf(project({ focusNodeId: "w1" }))).has("w1")).toBe(false);
  });
});

describe("可见边", () => {
  it("只有两端都可见的 hierarchy 边被保留", () => {
    const result = project();
    const ids = result.visibleEdges.map((e) => e.id);
    expect(ids).toContain("o1->v1");
    expect(ids).toContain("o1->v2");
    expect(ids).not.toContain("v1->p1");
  });

  it("默认不显示 sequence 与 reference 边", () => {
    const result = project({ expandedNodeIds: new Set(["v1", "p1"]) });
    const ids = result.visibleEdges.map((e) => e.id);
    expect(ids).not.toContain("c1->c2");
    expect(ids).not.toContain("npc->c1");
  });

  it("选中节点时显示与它相关的 sequence 边", () => {
    const result = project({
      expandedNodeIds: new Set(["v1", "p1"]),
      selectedNodeId: "c1",
    });
    expect(result.visibleEdges.map((e) => e.id)).toContain("c1->c2");
  });

  it("与选中节点无关的关系边不绘制", () => {
    const result = project({
      expandedNodeIds: new Set(["v1", "p1"]),
      selectedNodeId: "c2",
    });
    expect(result.visibleEdges.map((e) => e.id)).not.toContain("npc->c1");
  });
});

describe("卫星节点", () => {
  it("默认不出现在画布上", () => {
    expect(new Set(idsOf(project())).has("npc")).toBe(false);
  });

  it("选中结构节点时带出与之关联的配角", () => {
    const result = project({
      expandedNodeIds: new Set(["v1", "p1"]),
      selectedNodeId: "c1",
    });
    expect(result.visibleNodeIds.has("npc")).toBe(true);
    expect(result.satelliteAnchorById.get("npc")).toBe("c1");
    expect(result.visibleEdges.map((e) => e.id)).toContain("npc->c1");
  });

  it("卫星节点不参与树深度", () => {
    const result = project({
      expandedNodeIds: new Set(["v1", "p1"]),
      selectedNodeId: "c1",
    });
    expect(result.depthById.has("npc")).toBe(false);
  });

  it("选中其他节点时卫星节点消失", () => {
    const result = project({
      expandedNodeIds: new Set(["v1", "p1"]),
      selectedNodeId: "c2",
    });
    expect(result.visibleNodeIds.has("npc")).toBe(false);
  });

  it("孤立节点不会作为卫星节点被带出", () => {
    // worldbuilding / note / 主角禁止任何连线，不存在把它们带上画布的路径
    const result = project({
      expandedNodeIds: new Set(["v1", "p1"]),
      selectedNodeId: "c1",
    });
    expect(result.visibleNodeIds.has("w1")).toBe(false);
    expect(result.visibleNodeIds.has("hero")).toBe(false);
  });

  it("选中节点自身不可见时不带出卫星", () => {
    const result = project({ selectedNodeId: "c1" });
    expect(result.visibleNodeIds.has("npc")).toBe(false);
  });
});

describe("展开控件可见性", () => {
  it("有结构子节点时可展开", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(isNodeExpandable(index, "v1")).toBe(true);
  });

  it("没有结构子节点时不可展开", () => {
    const index = buildGraphIndex(nodes, edges);
    expect(isNodeExpandable(index, "c1")).toBe(false);
    expect(isNodeExpandable(index, "v2")).toBe(false);
  });
});

describe("toggleExpanded", () => {
  it("返回新集合，不修改原集合", () => {
    const original = new Set(["v1"]);
    const next = toggleExpanded(original, "p1");
    expect(next.has("p1")).toBe(true);
    expect(original.has("p1")).toBe(false);
  });

  it("再次调用会移除", () => {
    const next = toggleExpanded(new Set(["v1"]), "v1");
    expect(next.has("v1")).toBe(false);
  });
});

describe("空图", () => {
  it("没有节点时返回空结果", () => {
    const index = buildGraphIndex([], []);
    const result = projectVisibleGraph({ index, expandedNodeIds: new Set() });
    expect(result.visibleNodes).toEqual([]);
    expect(result.visibleEdges).toEqual([]);
  });
});
