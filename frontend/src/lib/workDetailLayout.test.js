import { describe, expect, it } from "vitest";
import {
  WORK_DETAIL_BODY_FLEX_CLASS,
  WORK_DETAIL_CONTENT_ROW_CLASS,
  WORK_DETAIL_SCROLL_PANE_CLASS,
  hasFlexScrollMinHeight,
} from "./workDetailLayout";

describe("workDetailLayout", () => {
  it("includes min-h-0 on flex scroll chain classes", () => {
    expect(hasFlexScrollMinHeight(WORK_DETAIL_BODY_FLEX_CLASS)).toBe(true);
    expect(hasFlexScrollMinHeight(WORK_DETAIL_CONTENT_ROW_CLASS)).toBe(true);
    expect(hasFlexScrollMinHeight(WORK_DETAIL_SCROLL_PANE_CLASS)).toBe(true);
  });
});
