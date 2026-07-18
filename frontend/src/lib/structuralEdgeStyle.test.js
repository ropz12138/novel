import { describe, expect, it } from "vitest";

import {
  CHARACTER_OUTGOING_EDGE_STYLE,
  getEdgeStyleByType,
  getStructuralEdgeStyle,
} from "./structuralEdgeStyle";

describe("structuralEdgeStyle", () => {
  it("uses preset styles for known edge types", () => {
    expect(getEdgeStyleByType("contains")).toEqual({
      stroke: "#f59e0b",
      strokeWidth: 2,
      strokeDasharray: "8,4",
    });
  });

  it("falls back to default for natural-language edge types", () => {
    expect(getEdgeStyleByType("角色出场")).toEqual({
      stroke: "#94a3b8",
      strokeWidth: 1.5,
    });
  });

  it("uses character outgoing style when source is character", () => {
    expect(getStructuralEdgeStyle("角色出场", "character")).toEqual(
      CHARACTER_OUTGOING_EDGE_STYLE,
    );
    expect(getStructuralEdgeStyle("contains", "character")).toEqual(
      CHARACTER_OUTGOING_EDGE_STYLE,
    );
  });

  it("keeps edge-type style when source is not character", () => {
    expect(getStructuralEdgeStyle("contains", "plot")).toEqual(
      getEdgeStyleByType("contains"),
    );
    expect(getStructuralEdgeStyle("角色出场", "chapter")).toEqual(
      getEdgeStyleByType("角色出场"),
    );
  });
});
