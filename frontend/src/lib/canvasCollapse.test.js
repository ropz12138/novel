import { describe, expect, it } from "vitest";

import {
  isContainsEdge,
  isDescendantOfCollapsed,
  buildElementChapterLinks,
  isElementHiddenByCollapsedChapters,
  isNodeHiddenByCollapse,
  buildCollapsibleNodeIds,
} from "./canvasCollapse";

const node = (id, type) => ({ id, data: { type } });
const edge = (id, source, target, edgeType = "contains") => ({
  id,
  source,
  target,
  data: { edge_type: edgeType },
});

describe("isContainsEdge", () => {
  it("recognizes contains and 包含", () => {
    expect(isContainsEdge("contains")).toBe(true);
    expect(isContainsEdge("包含")).toBe(true);
    expect(isContainsEdge("角色登场")).toBe(false);
  });
});

describe("chapter element collapse", () => {
  const nodes = [
    node("e1", "element"),
    node("e2", "element"),
    node("c1", "chapter"),
    node("c2", "chapter"),
  ];
  const edges = [
    edge("x1", "e1", "c1"),
    edge("x2", "e2", "c1"),
    edge("x3", "e2", "c2"), // e2 跨章复用
  ];
  const { elementToChapters, chapterToElements } = buildElementChapterLinks(edges, nodes);

  it("maps element→chapter contains links", () => {
    expect(chapterToElements.c1).toEqual(["e1", "e2"]);
    expect(chapterToElements.c2).toEqual(["e2"]);
    expect(elementToChapters.e2).toEqual(["c1", "c2"]);
  });

  it("hides elements when their chapter is collapsed", () => {
    const collapsed = new Set(["c1"]);
    expect(isElementHiddenByCollapsedChapters("e1", elementToChapters, collapsed)).toBe(true);
    expect(isElementHiddenByCollapsedChapters("e2", elementToChapters, collapsed)).toBe(false);
  });

  it("hides shared element only when all linked chapters collapsed", () => {
    const collapsed = new Set(["c1", "c2"]);
    expect(isElementHiddenByCollapsedChapters("e2", elementToChapters, collapsed)).toBe(true);
  });

  it("isNodeHiddenByCollapse hides element but keeps chapter visible", () => {
    const parentMap = {};
    const collapsed = new Set(["c1"]);
    const nodeTypeById = new Map(nodes.map((n) => [n.id, n.data.type]));

    expect(isNodeHiddenByCollapse("c1", {
      parentMap,
      collapsedNodeIds: collapsed,
      elementToChapters,
      nodeTypeById,
    })).toBe(false);
    expect(isNodeHiddenByCollapse("e1", {
      parentMap,
      collapsedNodeIds: collapsed,
      elementToChapters,
      nodeTypeById,
    })).toBe(true);
  });
});

describe("isDescendantOfCollapsed (structural tree)", () => {
  const parentMap = { ch1: "root", g1: "ch1" };

  it("hides descendants when ancestor collapsed", () => {
    expect(isDescendantOfCollapsed("g1", parentMap, new Set(["ch1"]))).toBe(true);
    expect(isDescendantOfCollapsed("root", parentMap, new Set(["root"]))).toBe(false);
  });
});

describe("buildCollapsibleNodeIds", () => {
  it("includes chapters that have linked elements", () => {
    const ids = buildCollapsibleNodeIds(
      new Set(["plot1"]),
      { c1: ["e1"], c2: [] },
    );
    expect(ids.has("plot1")).toBe(true);
    expect(ids.has("c1")).toBe(true);
    expect(ids.has("c2")).toBe(false);
  });
});
