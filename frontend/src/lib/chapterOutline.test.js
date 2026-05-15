import { describe, expect, it } from "vitest";
import { extractChapterNumbers } from "./chapterOutline.js";

describe("extractChapterNumbers", () => {
  it("returns empty array when outline is null or undefined", () => {
    expect(extractChapterNumbers(null)).toEqual([]);
    expect(extractChapterNumbers(undefined)).toEqual([]);
  });

  it("returns empty when timeline and branches are empty", () => {
    expect(extractChapterNumbers({ timeline: [], branches: [] })).toEqual([]);
  });

  it("builds 1..max from timeline chapter_end", () => {
    const tree = {
      timeline: [
        { chapter_start: 1, chapter_end: 3 },
        { chapter_start: 4, chapter_end: 5 },
      ],
      branches: [],
    };
    expect(extractChapterNumbers(tree)).toEqual([1, 2, 3, 4, 5]);
  });

  it("includes max from branches", () => {
    const tree = {
      timeline: [{ chapter_start: 1, chapter_end: 2 }],
      branches: [{ chapter_start: 10, chapter_end: 12 }],
    };
    expect(extractChapterNumbers(tree)).toEqual(
      Array.from({ length: 12 }, (_, i) => i + 1),
    );
  });
});
