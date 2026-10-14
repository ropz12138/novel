import { describe, expect, it } from "vitest";
import { composerKeyboardOffset, editorScrollDelta } from "./keyboardInset";

describe("composerKeyboardOffset", () => {
  it("is zero when the visual viewport fills the window", () => {
    expect(composerKeyboardOffset(800, { height: 800, offsetTop: 0 })).toBe(0);
  });

  it("lifts by the covered keyboard height", () => {
    expect(composerKeyboardOffset(800, { height: 500, offsetTop: 0 })).toBe(300);
  });

  it("uses the stable pre-keyboard height when Android shrinks innerHeight", () => {
    const stableViewportHeight = 800;
    const currentInnerHeight = 500;

    expect(currentInnerHeight).toBe(500);
    expect(composerKeyboardOffset(stableViewportHeight, { height: 500, offsetTop: 0 })).toBe(300);
  });
});

describe("editorScrollDelta", () => {
  it("scrolls only enough to place a covered editor above the keyboard", () => {
    expect(editorScrollDelta({ bottom: 690 }, 500)).toBe(206);
  });

  it("does not scroll an editor that is already visible", () => {
    expect(editorScrollDelta({ bottom: 420 }, 500)).toBe(0);
  });
});
