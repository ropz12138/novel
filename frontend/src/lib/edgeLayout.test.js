import { describe, expect, it } from "vitest";

import {
  applyEdgeLabelAvoidance,
  computeEdgeLayoutDiagnostics,
  normalizeEdgeLayout,
  resolveOptimalSides,
  edgeHandlesFromSides,
  applyEdgeHandles,
  isHierarchyChainEdge,
  resolveHierarchyChainSides,
} from "./edgeLayout";
import { ELEMENT_SIZE, NODE_HEIGHT, NODE_WIDTH } from "./nodeDimensions";

const node = (id, x, y, type = "outline") => {
  const isElement = type === "element";
  return {
    id,
    position: { x, y },
    width: isElement ? ELEMENT_SIZE : NODE_WIDTH,
    height: isElement ? ELEMENT_SIZE : NODE_HEIGHT,
    data: { type },
  };
};

const edge = (id, source, target, extra_data = {}, label = "关系文本") => ({
  id,
  source,
  target,
  label,
  data: { edge_type: "关系", extra_data },
});

describe("edge layout", () => {
  it("resolveOptimalSides uses element outer boundary for close diagonal layout", () => {
    expect(resolveOptimalSides(node("a", 0, 0, "element"), node("b", 50, 100, "chapter"))).toEqual({
      source_side: "right",
      target_side: "left",
    });
  });

  it("resolveOptimalSides picks vertical handles for stacked nodes", () => {
    expect(resolveOptimalSides(node("a", 0, 0, "element"), node("b", 0, 300, "character"))).toEqual({
      source_side: "bottom",
      target_side: "top",
    });
  });

  it("resolveOptimalSides picks horizontal handles for side-by-side nodes", () => {
    expect(resolveOptimalSides(node("a", 0, 0, "element"), node("b", 400, 0, "chapter"))).toEqual({
      source_side: "right",
      target_side: "left",
    });
  });

  it("hierarchy chain nodes always use bottom to top", () => {
    expect(isHierarchyChainEdge(
      node("o", 0, 0, "outline"),
      node("v", 500, 0, "volume"),
    )).toBe(true);
    expect(resolveOptimalSides(
      node("o", 0, 0, "outline"),
      node("v", 500, 0, "volume"),
    )).toEqual(resolveHierarchyChainSides());
    expect(resolveOptimalSides(
      node("p", 0, 100, "plot"),
      node("c", 0, 500, "chapter"),
    )).toEqual({ source_side: "bottom", target_side: "top" });
  });

  it("resolveOptimalSides reverses when target is above source", () => {
    expect(resolveOptimalSides(node("a", 0, 300, "element"), node("b", 0, 0, "character"))).toEqual({
      source_side: "top",
      target_side: "bottom",
    });
  });

  it("applyEdgeHandles assigns structural handles from node positions", () => {
    const nodes = [node("a", 0, 0, "element"), node("b", 400, 0, "chapter")];
    const [laidOut] = applyEdgeHandles(nodes, [edge("e1", "a", "b")]);
    expect(laidOut.sourceHandle).toBe("source-right");
    expect(laidOut.targetHandle).toBe("target-left");
  });

  it("applyEdgeHandles uses bottom-top for hierarchy chain edges", () => {
    const nodes = [node("a", 0, 0, "outline"), node("b", 400, 0, "volume")];
    const [laidOut] = applyEdgeHandles(nodes, [edge("e1", "a", "b")]);
    expect(laidOut.sourceHandle).toBe("source-bottom");
    expect(laidOut.targetHandle).toBe("target-top");
  });

  it("chapter-to-chapter edges always use right to left", () => {
    expect(resolveOptimalSides(
      node("c1", 0, 0, "chapter"),
      node("c2", 400, 0, "chapter"),
    )).toEqual({ source_side: "right", target_side: "left" });
    expect(resolveOptimalSides(
      node("c1", 400, 0, "chapter"),
      node("c2", 0, 300, "chapter"),
    )).toEqual({ source_side: "right", target_side: "left" });
    const nodes = [node("c1", 0, 0, "chapter"), node("c2", 400, 0, "chapter")];
    const [laidOut] = applyEdgeHandles(nodes, [edge("e1", "c1", "c2")]);
    expect(laidOut.sourceHandle).toBe("source-right");
    expect(laidOut.targetHandle).toBe("target-left");
  });

  it("applyEdgeHandles assigns relation handles with rel- prefix", () => {
    const nodes = [node("a", 0, 0, "character"), node("b", 0, 300, "character")];
    const [laidOut] = applyEdgeHandles(
      nodes,
      [edge("e1", "a", "b")],
      { relation: true },
    );
    expect(laidOut.sourceHandle).toBe("rel-source-bottom");
    expect(laidOut.targetHandle).toBe("rel-target-top");
  });

  it("edgeHandlesFromSides supports relation prefix", () => {
    expect(edgeHandlesFromSides(
      { source_side: "right", target_side: "left" },
      { relation: true },
    )).toEqual({
      sourceHandle: "rel-source-right",
      targetHandle: "rel-target-left",
    });
  });

  it("normalizes agent-editable layout without label positioning fields", () => {
    expect(normalizeEdgeLayout({
      layout: {
        source_side: "right",
        target_side: "left",
        curvature: 0.4,
        lane: 2,
        routing_offset: 90,
      },
    })).toEqual({
      source_side: "right",
      target_side: "left",
      curvature: 0.4,
      lane: 2,
      routing_offset: 90,
      manually_positioned: false,
    });
  });

  it("detects strongly overlapping curves", () => {
    const nodes = [node("a", 0, 0), node("b", 0, 300)];
    const diagnostics = computeEdgeLayoutDiagnostics(nodes, [
      edge("e1", "a", "b"),
      edge("e2", "a", "b"),
    ]);

    expect(diagnostics[0].issues).toEqual(expect.arrayContaining([
      expect.objectContaining({
        type: "edge_overlap",
        other_edge_id: "e2",
        severity: "high",
      }),
    ]));
  });

  it("separates colliding relation labels when a free candidate exists", () => {
    const nodes = [node("a", 0, 0), node("b", 0, 300)];
    const laidOut = applyEdgeLabelAvoidance(nodes, [
      edge("e1", "a", "b"),
      edge("e2", "a", "b"),
    ]);

    expect(laidOut[0].data.label_position).toBeDefined();
    expect(laidOut[1].data.label_position).toBeDefined();
    expect(laidOut[1].data.label_position).not.toEqual(
      laidOut[0].data.label_position,
    );
  });
});
