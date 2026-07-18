import { describe, expect, it } from "vitest";
import {
  filterGraphAfterNodeRemoval,
  getDeletableSelectedNodeIds,
  isCanvasDeleteKey,
  shouldIgnoreCanvasKeyEvent,
} from "./canvasDelete";

describe("canvasDelete", () => {
  it("ignores delete keys inside editable targets", () => {
    const input = document.createElement("input");
    expect(shouldIgnoreCanvasKeyEvent({ target: input })).toBe(true);
    expect(isCanvasDeleteKey({ key: "Delete", target: document.body, ctrlKey: false, metaKey: false, altKey: false })).toBe(true);
  });

  it("detects Delete and Backspace without modifiers", () => {
    expect(isCanvasDeleteKey({ key: "Delete", ctrlKey: false, metaKey: false, altKey: false })).toBe(true);
    expect(isCanvasDeleteKey({ key: "Backspace", ctrlKey: false, metaKey: false, altKey: false })).toBe(true);
    expect(isCanvasDeleteKey({ key: "Delete", ctrlKey: true, metaKey: false, altKey: false })).toBe(false);
  });

  it("collects selected visible node ids", () => {
    const ids = getDeletableSelectedNodeIds([
      { id: "n1", selected: true },
      { id: "n2", selected: true, hidden: true },
      { id: "n3", selected: false },
    ]);
    expect(ids).toEqual(["n1"]);
  });

  it("filters nodes, edges, and character relations after removal", () => {
    const result = filterGraphAfterNodeRemoval(
      ["n1"],
      [{ id: "n1" }, { id: "n2" }],
      [
        { id: "e1", source: "n1", target: "n2" },
        { id: "e2", source: "n2", target: "n3" },
      ],
      [{ id: "r1", source: "n1", target: "n2" }],
    );

    expect(result.nodes.map((n) => n.id)).toEqual(["n2"]);
    expect(result.edges.map((e) => e.id)).toEqual(["e2"]);
    expect(result.characterRelations).toEqual([]);
  });
});
