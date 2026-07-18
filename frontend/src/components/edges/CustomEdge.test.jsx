import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

vi.mock("@xyflow/react", () => ({
  getBezierPath: () => ["M0,0 L100,100", 50, 50],
  EdgeLabelRenderer: ({ children }) => children,
}));

import CustomEdge from "./CustomEdge";

const defaultProps = {
  id: "test-edge",
  sourceX: 0,
  sourceY: 0,
  targetX: 100,
  targetY: 100,
  sourcePosition: "bottom",
  targetPosition: "top",
  style: { stroke: "#3b82f6", strokeWidth: 2 },
  markerEnd: { type: "arrowclosed" },
};

describe("CustomEdge", () => {
  it("renders short label without truncation", () => {
    render(
      <svg>
        <CustomEdge {...defaultProps} label="短标签" />
      </svg>
    );
    expect(screen.getByText("短标签")).toBeDefined();
  });

  it("truncates long label by default", () => {
    const longLabel = "这是一个很长的标签文本需要被截断显示测试截断功能";
    render(
      <svg>
        <CustomEdge {...defaultProps} label={longLabel} />
      </svg>
    );
    const truncated = screen.getByText(/...$/);
    expect(truncated).toBeDefined();
    expect(truncated.textContent.length).toBeLessThan(longLabel.length);
  });

  it("shows full label on hover", () => {
    const longLabel = "这是一个很长的标签文本需要被截断显示";
    render(
      <svg>
        <CustomEdge {...defaultProps} label={longLabel} />
      </svg>
    );

    const truncated = screen.getByText(/...$/);
    const hoverTarget = truncated.closest("div").parentElement;
    fireEvent.mouseEnter(hoverTarget);

    expect(screen.getByText(longLabel)).toBeDefined();
  });

  it("does not render label when label is empty", () => {
    const { container } = render(
      <svg>
        <CustomEdge {...defaultProps} label="" />
      </svg>
    );
    const labels = container.querySelectorAll("[data-testid]");
    expect(labels.length).toBe(0);
  });

  it("does not render label when label is undefined", () => {
    const { container } = render(
      <svg>
        <CustomEdge {...defaultProps} />
      </svg>
    );
    const labels = container.querySelectorAll("[data-testid]");
    expect(labels.length).toBe(0);
  });
});
