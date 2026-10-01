import { describe, expect, it } from "vitest";
import { composerKeyboardOffset } from "./keyboardInset";

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
