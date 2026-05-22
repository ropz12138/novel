import { describe, expect, it } from "vitest";
import {
  getRelationGraphLoadingMessage,
  relationGraphStabilizationFallbackMs,
} from "./relationGraphLoading";

describe("relationGraphStabilizationFallbackMs", () => {
  it("returns 0 when there are no nodes", () => {
    expect(relationGraphStabilizationFallbackMs(0, true)).toBe(0);
  });

  it("returns a short fallback when physics is disabled", () => {
    expect(relationGraphStabilizationFallbackMs(12, false)).toBe(300);
  });

  it("scales fallback with node count and caps at 10s", () => {
    expect(relationGraphStabilizationFallbackMs(10, true)).toBe(1850);
    expect(relationGraphStabilizationFallbackMs(500, true)).toBe(10000);
  });
});

describe("getRelationGraphLoadingMessage", () => {
  it("returns phase-specific copy", () => {
    expect(getRelationGraphLoadingMessage("script")).toContain("引擎");
    expect(getRelationGraphLoadingMessage("layout")).toContain("关系");
    expect(getRelationGraphLoadingMessage("stabilize")).toContain("布局");
  });

  it("falls back to default message for unknown phase", () => {
    expect(getRelationGraphLoadingMessage("unknown")).toBe("关系图谱加载中…");
  });
});
