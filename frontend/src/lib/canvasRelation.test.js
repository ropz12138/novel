import { describe, it, expect } from "vitest";
import { HIERARCHY_CHAIN, hierarchyLevel, deriveRelationKind, isHierarchyEdge,
  isCanvasStructuralType, isIsolatedType } from "./canvasRelation";
describe("章节与资料分组", () => {
  it("章节直接位于作品下", () => {
    expect(HIERARCHY_CHAIN).toEqual(["chapter"]);
    expect(hierarchyLevel("chapter")).toBe(0);
    expect(isCanvasStructuralType("chapter")).toBe(true);
    expect(isIsolatedType("chapter")).toBe(false);
    expect(deriveRelationKind("chapter", "chapter")).toBeNull();
  });
  it("旧类型既不显示在画布也不显示在资料栏", () => {
    for (const type of ["outline", "volume", "plot"]) {
      expect(isCanvasStructuralType(type)).toBe(false);
      expect(isIsolatedType(type)).toBe(false);
      expect(deriveRelationKind(type, "chapter")).toBeNull();
      expect(isHierarchyEdge({ source: "old", target: "c" }, new Map([["old", type], ["c", "chapter"]]))).toBe(false);
    }
  });
  it("角色、世界观和笔记属于侧栏", () => {
    for (const type of ["character", "worldbuilding", "note", "reviewer_note"]) {
      expect(isIsolatedType(type)).toBe(true);
      expect(isCanvasStructuralType(type)).toBe(false);
    }
    expect(isIsolatedType(undefined)).toBe(false);
  });
});
