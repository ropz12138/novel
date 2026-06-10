import { describe, expect, it, vi } from "vitest";
import {
  CHAPTER_TEXTAREA_MIN_HEIGHT_PX,
  applyChapterTextareaAutoHeight,
  bindChapterTextareaResizeObserver,
  resolveChapterTextareaHeightPx,
} from "./chapterTextareaHeight";

describe("resolveChapterTextareaHeightPx", () => {
  it("uses minimum height when content is shorter", () => {
    expect(resolveChapterTextareaHeightPx(40)).toBe(CHAPTER_TEXTAREA_MIN_HEIGHT_PX);
  });

  it("uses scroll height when content is taller", () => {
    expect(resolveChapterTextareaHeightPx(2400)).toBe(2400);
  });
});

describe("applyChapterTextareaAutoHeight", () => {
  it("clears inline height when content is empty", () => {
    const textarea = document.createElement("textarea");
    textarea.style.height = "3000px";
    applyChapterTextareaAutoHeight(textarea, { content: "" });
    expect(textarea.style.height).toBe("");
  });

  it("resets height to auto before applying new height", () => {
    const textarea = document.createElement("textarea");
    textarea.style.height = "3000px";
    textarea.value = "短正文";
    document.body.appendChild(textarea);
    applyChapterTextareaAutoHeight(textarea, { content: "短正文" });
    const applied = parseInt(textarea.style.height, 10);
    expect(applied).toBeLessThan(3000);
    textarea.remove();
  });
});

describe("bindChapterTextareaResizeObserver", () => {
  it("invokes callback when resize observer fires", () => {
    const textarea = document.createElement("textarea");
    const onResize = vi.fn();
    let trigger = () => {};
    const disconnect = vi.fn();
    global.ResizeObserver = vi.fn(function ResizeObserver(callback) {
      trigger = () => callback();
      this.observe = vi.fn();
      this.disconnect = disconnect;
    });

    const cleanup = bindChapterTextareaResizeObserver(textarea, onResize);
    trigger();
    expect(onResize).toHaveBeenCalledTimes(1);
    cleanup();
    expect(disconnect).toHaveBeenCalledTimes(1);
  });

  it("returns noop cleanup when textarea is missing", () => {
    expect(() => bindChapterTextareaResizeObserver(null, () => {})).not.toThrow();
  });
});
