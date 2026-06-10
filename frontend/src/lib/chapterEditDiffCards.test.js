import { describe, expect, it } from "vitest";
import { suppressSupersededChapterEditCards } from "./chapterEditDiffCards";

describe("suppressSupersededChapterEditCards", () => {
  it("removes non-readonly card when readonly exists for same chapter", () => {
    const items = [
      {
        kind: "message",
        type: "edit_diff_card",
        diffCard: { chapter_number: 1, readonly: false, summary: { lines_added: 11 } },
      },
      {
        kind: "message",
        type: "edit_diff_card",
        diffCard: { chapter_number: 1, readonly: true, summary: { lines_added: 11 } },
      },
    ];
    const result = suppressSupersededChapterEditCards(items);
    expect(result).toHaveLength(1);
    expect(result[0].diffCard.readonly).toBe(true);
  });

  it("keeps non-readonly card when no readonly card for chapter", () => {
    const items = [
      {
        kind: "message",
        type: "edit_diff_card",
        diffCard: { chapter_number: 2, readonly: false },
      },
    ];
    expect(suppressSupersededChapterEditCards(items)).toHaveLength(1);
  });
});
