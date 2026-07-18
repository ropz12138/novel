import { describe, expect, it } from "vitest";
import {
  isIllustrationApiPath,
  resolveIllustrationFetchUrl,
} from "./AuthIllustrationImage";

describe("AuthIllustrationImage helpers", () => {
  it("detects illustration API paths", () => {
    expect(isIllustrationApiPath("/api/illustrations/abc-123")).toBe(true);
    expect(isIllustrationApiPath("https://example.com/x.png")).toBe(false);
  });

  it("resolves relative illustration URL against API base", () => {
    expect(resolveIllustrationFetchUrl("/api/illustrations/id-1")).toBe(
      "http://127.0.0.1:9001/api/illustrations/id-1",
    );
  });
});
