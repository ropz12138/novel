import { describe, expect, it } from "vitest";
import { attachModifiedNodes } from "./modifiedNodeDraft";

describe("modified node draft", () => {
  const nodes = [{ id: "n1", type: "chapter", label: "第一章" }];
  it("includes modifications in the same user message", () => {
    expect(attachModifiedNodes("继续", nodes, "s1"))
      .toBe("[[ctx|n1|chapter|已修改：第一章]]\n继续");
  });
  it("omits removed capsules and modifications in a new session", () => {
    expect(attachModifiedNodes("继续", [], "s1")).toBe("继续");
    expect(attachModifiedNodes("继续", nodes, null)).toBe("继续");
  });
});
