import { describe, it, expect } from "vitest";
import {
  RELATION_HIERARCHY,
  RELATION_REFERENCE,
  HIERARCHY_CHAIN,
  hierarchyLevel,
  deriveRelationKind,
  isHierarchyEdge,
  edgeRelationKind,
  isCanvasStructuralType,
  isIsolatedType,
} from "./canvasRelation";

const flowEdge = (source, target, edgeType = "包含") => ({
  id: `${source}-${target}`,
  source,
  target,
  data: { edge_type: edgeType },
});

describe("hierarchyLevel", () => {
  it("层级链顺序与后端一致", () => {
    expect(HIERARCHY_CHAIN).toEqual(["outline", "volume", "plot", "chapter"]);
    expect(hierarchyLevel("outline")).toBe(0);
    expect(hierarchyLevel("volume")).toBe(1);
    expect(hierarchyLevel("plot")).toBe(2);
    expect(hierarchyLevel("chapter")).toBe(3);
  });

  it("非层级链类型返回 null", () => {
    expect(hierarchyLevel("character")).toBeNull();
    expect(hierarchyLevel("worldbuilding")).toBeNull();
    expect(hierarchyLevel("note")).toBeNull();
    expect(hierarchyLevel(undefined)).toBeNull();
  });
});

describe("deriveRelationKind", () => {
  it("严格降一级为 hierarchy", () => {
    expect(deriveRelationKind("outline", "volume")).toBe(RELATION_HIERARCHY);
    expect(deriveRelationKind("volume", "plot")).toBe(RELATION_HIERARCHY);
    expect(deriveRelationKind("plot", "chapter")).toBe(RELATION_HIERARCHY);
  });

  it("chapter → chapter 非法：同级顺序由 sort_order 表达", () => {
    // 若判据只看"两端都是层级链类型"，前一章会被当成后一章的父节点，树深度错乱
    const kind = deriveRelationKind("chapter", "chapter");
    expect(kind).toBeNull();
    expect(kind).not.toBe(RELATION_HIERARCHY);
  });

  it("同类型层级链节点之间一律非法", () => {
    expect(deriveRelationKind("volume", "volume")).toBeNull();
    expect(deriveRelationKind("plot", "plot")).toBeNull();
    expect(deriveRelationKind("outline", "outline")).toBeNull();
  });

  it("非层级链参与的边是 reference", () => {
    expect(deriveRelationKind("character", "chapter")).toBe(RELATION_REFERENCE);
    expect(deriveRelationKind("character", "plot")).toBe(RELATION_REFERENCE);
    expect(deriveRelationKind("worldbuilding", "note")).toBe(RELATION_REFERENCE);
  });

  it("跨级与反向返回 null", () => {
    expect(deriveRelationKind("outline", "plot")).toBeNull();
    expect(deriveRelationKind("outline", "chapter")).toBeNull();
    expect(deriveRelationKind("volume", "chapter")).toBeNull();
    expect(deriveRelationKind("volume", "outline")).toBeNull();
    expect(deriveRelationKind("chapter", "plot")).toBeNull();
  });
});

describe("edgeRelationKind / isHierarchyEdge", () => {
  const nodeTypeById = new Map([
    ["o1", "outline"],
    ["v1", "volume"],
    ["v2", "volume"],
    ["p1", "plot"],
    ["c1", "chapter"],
    ["c2", "chapter"],
    ["ch1", "character"],
  ]);

  it("自然语言 edge_type 不影响判定", () => {
    // edge_type 写"包含"，但 chapter → chapter 仍是非法的同级组合
    expect(edgeRelationKind(flowEdge("c1", "c2", "包含"), nodeTypeById)).toBeNull();
    // edge_type 写"参与"，但 volume → plot 仍是 hierarchy
    expect(edgeRelationKind(flowEdge("v1", "p1", "参与"), nodeTypeById)).toBe(
      RELATION_HIERARCHY,
    );
  });

  it("isHierarchyEdge 只对严格降一级的边为真", () => {
    expect(isHierarchyEdge(flowEdge("o1", "v1"), nodeTypeById)).toBe(true);
    expect(isHierarchyEdge(flowEdge("v1", "p1"), nodeTypeById)).toBe(true);
    expect(isHierarchyEdge(flowEdge("p1", "c1"), nodeTypeById)).toBe(true);
    expect(isHierarchyEdge(flowEdge("c1", "c2"), nodeTypeById)).toBe(false);
    expect(isHierarchyEdge(flowEdge("ch1", "c1"), nodeTypeById)).toBe(false);
    expect(isHierarchyEdge(flowEdge("o1", "c1"), nodeTypeById)).toBe(false);
  });

  it("端点类型缺失时不判为 hierarchy", () => {
    expect(isHierarchyEdge(flowEdge("unknown", "v1"), nodeTypeById)).toBe(false);
  });
});

describe("节点类型分组", () => {
  it("层级链类型参与画布树结构", () => {
    expect(isCanvasStructuralType("outline")).toBe(true);
    expect(isCanvasStructuralType("volume")).toBe(true);
    expect(isCanvasStructuralType("plot")).toBe(true);
    expect(isCanvasStructuralType("chapter")).toBe(true);
    expect(isCanvasStructuralType("character")).toBe(false);
    expect(isCanvasStructuralType("worldbuilding")).toBe(false);
  });

  it("所有非层级链节点都归入侧栏，不进入画布主干", () => {
    expect(isIsolatedType("worldbuilding")).toBe(true);
    expect(isIsolatedType("note")).toBe(true);
    expect(isIsolatedType("character")).toBe(true);
  });

  it("判定不依赖 scope：配角同样需要侧栏入口", () => {
    // 配角只在选中关联结构节点时作为卫星出现，若不进侧栏就没有任何常驻入口
    for (const scope of ["global", "major", "minor", "temp"]) {
      expect(isIsolatedType("character", scope)).toBe(true);
    }
  });

  it("层级链节点不是孤立节点", () => {
    expect(isIsolatedType("chapter", "local")).toBe(false);
    expect(isIsolatedType("outline", "local")).toBe(false);
  });
});
