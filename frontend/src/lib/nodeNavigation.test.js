import { describe, expect, it } from "vitest";
import { firstOutlineNode, orderedNavigationNodes } from "./nodeNavigation";

describe("orderedNavigationNodes", () => {
  it("visits siblings before the first node of the next level", () => {
    const nodes = [
      { id: "chapter", data: { type: "chapter", sort_order: 1 } },
      { id: "plot", data: { type: "plot", sort_order: 1 } },
      { id: "volume-2", data: { type: "volume", sort_order: 2 } },
      { id: "volume-1", data: { type: "volume", sort_order: 1 } },
      { id: "outline", data: { type: "outline", sort_order: 1 } },
    ];
    expect(orderedNavigationNodes(nodes).map((node) => node.id)).toEqual([
      "outline", "volume-1", "volume-2", "plot", "chapter",
    ]);
  });

  it("keeps isolated node groups navigable", () => {
    const nodes = [
      { id: "note", data: { type: "note", sort_order: 1 } },
      { id: "character", data: { type: "character", sort_order: 1 } },
      { id: "world", data: { type: "worldbuilding", sort_order: 1 } },
    ];
    expect(orderedNavigationNodes(nodes).map((node) => node.id)).toEqual(["character", "world", "note"]);
  });
});

describe("firstOutlineNode", () => {
  it("picks the earliest outline when several exist", () => {
    const nodes = [
      { id: "o2", data: { type: "outline", sort_order: 2 } },
      { id: "v1", data: { type: "volume", sort_order: 1 } },
      { id: "o1", data: { type: "outline", sort_order: 1 } },
    ];
    expect(firstOutlineNode(nodes)?.id).toBe("o1");
  });

  it("returns null when the canvas has no outline", () => {
    expect(firstOutlineNode([
      { id: "v1", data: { type: "volume", sort_order: 1 } },
    ])).toBeNull();
  });
});
