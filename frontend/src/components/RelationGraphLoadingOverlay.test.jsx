import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { RelationGraphLoadingOverlay } from "./RelationGraphLoadingOverlay";

describe("RelationGraphLoadingOverlay", () => {
  it("renders mesh animation and phase message", () => {
    const html = renderToString(<RelationGraphLoadingOverlay phase="stabilize" />);
    expect(html).toContain("relation-graph-loading-mesh");
    expect(html).toContain("正在稳定节点布局");
    expect(html).toContain('aria-busy="true"');
  });

  it("renders default message when phase is omitted", () => {
    const html = renderToString(<RelationGraphLoadingOverlay />);
    expect(html).toContain("关系图谱加载中…");
  });
});
