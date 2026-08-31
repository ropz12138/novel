import { describe, it, expect } from "vitest";
import {
  RELATION_HIERARCHY,
  RELATION_SEQUENCE,
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

  it("chapter → chapter 是 sequence 而不是 hierarchy", () => {
    // 若判据只看"两端都是层级链类型"，前一章会被当成后一章的父节点，树深度错乱
    const kind = deriveRelationKind("chapter", "chapter");
    expect(kind).toBe(RELATION_SEQUENCE);
    expect(kind).not.toBe(RELATION_HIERARCHY);
  });

  it("同类型层级链节点之间是 sequence", () => {
    expect(deriveRelationKind("volume", "volume")).toBe(RELATION_SEQUENCE);
    expect(deriveRelationKind("plot", "plot")).toBe(RELATION_SEQUENCE);
    expect(deriveRelationKind("outline", "outline")).toBe(RELATION_SEQUENCE);
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
    // edge_type 写"包含"，但 chapter → chapter 仍是 sequence
    expect(edgeRelationKind(flowEdge("c1", "c2", "包含"), nodeTypeById)).toBe(
      RELATION_SEQUENCE,
    );
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

  it("禁止连线的节点为孤立节点，不进入画布", () => {
    // 后端规定 scope=global 的节点禁止任何连线：worldbuilding / note / 主角
    expect(isIsolatedType("worldbuilding", "global")).toBe(true);
    expect(isIsolatedType("note", "global")).toBe(true);
    expect(isIsolatedType("character", "global")).toBe(true);
  });

  it("有关联边的配角不是孤立节点", () => {
    expect(isIsolatedType("character", "major")).toBe(false);
    expect(isIsolatedType("character", "minor")).toBe(false);
    expect(isIsolatedType("character", "temp")).toBe(false);
  });

  it("层级链节点不是孤立节点", () => {
    expect(isIsolatedType("chapter", "local")).toBe(false);
    expect(isIsolatedType("outline", "local")).toBe(false);
  });
});
