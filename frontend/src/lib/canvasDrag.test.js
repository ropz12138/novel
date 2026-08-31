import { describe, expect, it } from "vitest";
import {
  CANVAS_MARQUEE_KEY_CODE,
  shouldClearDrawerOnSelection,
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
});
