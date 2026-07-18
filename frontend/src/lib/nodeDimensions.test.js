import { describe, expect, it } from "vitest";

import {
  ELEMENT_SIZE,
  NODE_HEIGHT,
  NODE_WIDTH,
  anchorOnOuterBoundary,
  flowNodeDimensionsFromRaw,
  getNodeDimensions,
  nodeBoundsFromFlowNode,
} from "./nodeDimensions";

describe("nodeDimensions", () => {
  it("uses 90x90 bounds for element nodes", () => {
    const node = {
      id: "e1",
      position: { x: 10, y: 20 },
      data: { type: "element" },
    };
    expect(getNodeDimensions(node)).toEqual({
      width: ELEMENT_SIZE,
      height: ELEMENT_SIZE,
    });
    expect(nodeBoundsFromFlowNode(node)).toEqual({
      x: 10,
      y: 20,
      width: ELEMENT_SIZE,
      height: ELEMENT_SIZE,
      right: 10 + ELEMENT_SIZE,
      bottom: 20 + ELEMENT_SIZE,
    });
  });

  it("uses default rect bounds for non-element nodes", () => {
    const node = {
      id: "c1",
      position: { x: 0, y: 0 },
      data: { type: "chapter" },
    };
    expect(getNodeDimensions(node)).toEqual({
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    });
  });

  it("places anchors on the outer boundary midpoints", () => {
    const bounds = { x: 0, y: 0, width: 90, height: 90, right: 90, bottom: 90 };
    expect(anchorOnOuterBoundary(bounds, "top")).toEqual({ x: 45, y: 0 });
    expect(anchorOnOuterBoundary(bounds, "right")).toEqual({ x: 90, y: 45 });
    expect(anchorOnOuterBoundary(bounds, "bottom")).toEqual({ x: 45, y: 90 });
    expect(anchorOnOuterBoundary(bounds, "left")).toEqual({ x: 0, y: 45 });
  });

  it("maps raw backend nodes to flow dimensions", () => {
    expect(flowNodeDimensionsFromRaw({ type: "element" })).toEqual({
      width: ELEMENT_SIZE,
      height: ELEMENT_SIZE,
    });
    expect(flowNodeDimensionsFromRaw({ type: "chapter" })).toEqual({
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    });
  });
});
