import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("@xyflow/react", () => ({
  Handle: () => null,
  Position: { Top: "top", Right: "right", Bottom: "bottom", Left: "left" },
}));

import CustomNode from "./CustomNode";


describe("CustomNode chapter status", () => {
  it("uses the fixed dimensions shared with backend layout diagnostics", () => {
    const { container } = render(
      <CustomNode
        id="node-1"
        data={{ type: "outline", label: "主线", content: "", extra_data: {} }}
      />,
    );

    const node = container.firstChild;
    expect(node.className).toContain("w-[250px]");
    expect(node.className).toContain("h-[120px]");
  });

  it("shows chapter word count and sync status", () => {
    render(
      <CustomNode
        id="chapter-1"
        data={{
          type: "chapter",
          label: "第一章",
          content: "林川 进入\n档案室",
          extra_data: {
            last_generation: {
              sync_evaluations: [{ passed: true }],
            },
          },
        }}
      />,
    );

    expect(screen.getByText("7 字")).toBeDefined();
    expect(screen.getByText("同步通过")).toBeDefined();
  });

  it("shows unwritten chapter without a sync badge", () => {
    render(
      <CustomNode
        id="chapter-2"
        data={{
          type: "chapter",
          label: "第二章",
          content: "",
          extra_data: {},
        }}
      />,
    );

    expect(screen.getByText("未写")).toBeDefined();
    expect(screen.queryByText("同步通过")).toBeNull();
  });

  it("uses a dedicated button to toggle related edges without opening the node", () => {
    const onNodeClick = vi.fn();
    const onFocusEdges = vi.fn();
    render(
      <CustomNode
        id="chapter-3"
        data={{ type: "chapter", label: "第三章", content: "", extra_data: {} }}
        onNodeClick={onNodeClick}
        onFocusEdges={onFocusEdges}
        isEdgesFocused={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "只显示相关连线" }));
    expect(onFocusEdges).toHaveBeenCalledWith("chapter-3");
    expect(onNodeClick).not.toHaveBeenCalled();
  });

  it("does not show collapse toggle on element nodes", () => {
    render(
      <CustomNode
        id="el-1"
        data={{ type: "element", label: "伏笔", content: "", extra_data: {} }}
        hasChildren
        isCollapsed={false}
        onCollapseToggle={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "收起子节点" })).toBeNull();
    expect(screen.queryByRole("button", { name: "展开子节点" })).toBeNull();
  });

  it("uses 90x90 outer boundary for element nodes", () => {
    const { container } = render(
      <CustomNode
        id="el-2"
        data={{ type: "element", label: "伏笔", content: "", extra_data: {} }}
      />,
    );

    const node = container.firstChild;
    expect(node.style.width).toBe("90px");
    expect(node.style.height).toBe("90px");
  });

  it("renders element nodes with reflective 3d surface layers", () => {
    const { container } = render(
      <CustomNode
        id="el-3"
        data={{ type: "element", label: "伏笔", content: "", extra_data: {} }}
      />,
    );

    const node = container.firstChild;
    expect(node.className).toContain("element-node-3d");
    expect(node.querySelector(".element-node-shine")).toBeTruthy();
    expect(node.querySelector(".element-node-reflection")).toBeTruthy();
    expect(node.style.getPropertyValue("--element-fill-opacity")).toBe("0.76");
  });
});

describe("CustomNode character scope badge", () => {
  it("shows protagonist badge for global character", () => {
    render(
      <CustomNode
        id="c1"
        data={{ type: "character", label: "林川", content: "", extra_data: {}, scope: "global" }}
      />,
    );
    expect(screen.getByText("主角")).toBeDefined();
  });

  it("shows major / minor badges", () => {
    const { unmount } = render(
      <CustomNode id="c2" data={{ type: "character", label: "王五", content: "", extra_data: {}, scope: "major" }} />,
    );
    expect(screen.getByText("主要配角")).toBeDefined();
    unmount();

    render(
      <CustomNode id="c3" data={{ type: "character", label: "路人甲", content: "", extra_data: {}, scope: "minor" }} />,
    );
    expect(screen.getByText("次要配角")).toBeDefined();
  });

  it("shows temp badge with dashed border", () => {
    const { container } = render(
      <CustomNode id="c4" data={{ type: "character", label: "店小二", content: "", extra_data: {}, scope: "temp" }} />,
    );
    expect(screen.getByText("临时")).toBeDefined();
    expect(container.firstChild.className).toContain("border-dashed");
  });

  it("non-character keeps type badge regardless of scope", () => {
    render(
      <CustomNode id="o1" data={{ type: "outline", label: "主线", content: "", extra_data: {}, scope: "local" }} />,
    );
    expect(screen.getByText("大纲")).toBeDefined();
    expect(screen.queryByText("主角")).toBeNull();
  });
});
