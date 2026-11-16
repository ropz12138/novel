import { describe, expect, it } from "vitest";

import { paragraphSpan, splitAgentParagraphs } from "./agentParagraphs.js";

describe("agent paragraph references", () => {
  it("numbers the same spans the agent reads", () => {
    for (const content of ["甲\n\n\n\n乙", "甲\r\n\r\n乙", "甲\n \n乙"]) {
      const paragraphs = splitAgentParagraphs(content);
      expect(paragraphs.map((paragraph) => content.slice(paragraph.start, paragraph.end))).toEqual(["甲", "乙"]);
      expect(paragraphSpan(content, 2, 2)).toEqual({
        start: paragraphs[1].start,
        end: paragraphs[1].end,
      });
    }
  });

  it("rejects a missing paragraph and an inverted range", () => {
    expect(paragraphSpan("甲。\n\n乙。", 3, 3)).toBeNull();
    expect(paragraphSpan("甲。", 2, 1)).toBeNull();
  });
});
