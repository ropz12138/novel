import { describe, expect, it, vi } from "vitest";
import {
  CANVAS_MARQUEE_KEY_CODE,
  getMovedNodesFromSnapshot,
  persistNodePositionUpdates,
  shouldClearDrawerOnSelection,
  toNodePositionUpdates,
} from "./canvasDrag";

describe("canvasDrag", () => {
  it("uses Control as marquee selection key", () => {
    expect(CANVAS_MARQUEE_KEY_CODE).toBe("Control");
  });

  it("shouldClearDrawerOnSelection ignores changes while dragging", () => {
    expect(shouldClearDrawerOnSelection(1, true)).toBe(false);
    expect(shouldClearDrawerOnSelection(2, true)).toBe(false);
  });

  it("shouldClearDrawerOnSelection clears on empty or multi select when not dragging", () => {
    expect(shouldClearDrawerOnSelection(0, false)).toBe(true);
    expect(shouldClearDrawerOnSelection(2, false)).toBe(true);
    expect(shouldClearDrawerOnSelection(1, false)).toBe(false);
  });

  it("getMovedNodesFromSnapshot returns nodes whose position changed", () => {
    const snapshot = {
      nodes: [
        { id: "n1", position_x: 0, position_y: 0 },
        { id: "n2", position_x: 10, position_y: 10 },
      ],
    };
    const current = [
      { id: "n1", position: { x: 5, y: 0 } },
      { id: "n2", position: { x: 10, y: 10 } },
    ];
    const moved = getMovedNodesFromSnapshot(snapshot, current);
    expect(moved).toHaveLength(1);
    expect(moved[0].id).toBe("n1");
  });

  it("persistNodePositionUpdates calls updateNode for each moved node", async () => {
    const updateNodeFn = vi.fn().mockResolvedValue({});
    await persistNodePositionUpdates([
      { id: "n1", position: { x: 1, y: 2 } },
      { id: "n2", position: { x: 3, y: 4 } },
    ], updateNodeFn);
    expect(updateNodeFn).toHaveBeenCalledTimes(2);
    expect(updateNodeFn).toHaveBeenCalledWith("n1", { position_x: 1, position_y: 2 });
    expect(updateNodeFn).toHaveBeenCalledWith("n2", { position_x: 3, position_y: 4 });
  });
});
