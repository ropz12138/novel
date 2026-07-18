import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import NodeDetailDrawer from "./NodeDetailDrawer";

describe("NodeDetailDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("exports a default component", () => {
    expect(NodeDetailDrawer).toBeDefined();
    expect(typeof NodeDetailDrawer).toBe("function");
  });

  it("renders chapter content and latest sync result from node data", () => {
    const node = {
      id: "node-1",
      type: "chapter",
      label: "第一章",
      content: "林川进入档案室。",
      extra_data: {
        last_generation: {
          sync_evaluations: [
            {
              passed: true,
              plan_alignment: {
                completed: ["林川进入档案室", "顾岚阻止林川"],
                missing: [],
              },
            },
          ],
        },
      },
    };

    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(screen.getByText("林川进入档案室。")).toBeDefined();
    expect(screen.getByText("与画布规划同步")).toBeDefined();
    expect(screen.getByText("林川进入档案室", { exact: true })).toBeDefined();
    expect(screen.getByText("顾岚阻止林川")).toBeDefined();
    expect(screen.getByText("自动修订 0 次")).toBeDefined();
  });

  it("renders missing planning items when sync check fails", () => {
    const node = {
      id: "node-1",
      type: "chapter",
      label: "第一章",
      content: "正文",
      extra_data: {
        last_generation: {
          sync_evaluations: [
            {
              passed: false,
              plan_alignment: {
                completed: [],
                missing: ["章末发现移交单"],
              },
            },
          ],
        },
      },
    };

    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(screen.getByText("同步检查未通过")).toBeDefined();
    expect(screen.getByText("章末发现移交单")).toBeDefined();
  });

  it("renders nothing when node is null", () => {
    const { container } = render(<NodeDetailDrawer node={null} onClose={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it("restores the last scroll position when reopening the same node", async () => {
    const node = {
      id: "remember-scroll-node",
      type: "chapter",
      label: "第一章",
      content: "正文",
      extra_data: {},
    };
    const { rerender } = render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);
    const scrollContainer = screen.getByTestId("node-detail-scroll");

    fireEvent.scroll(scrollContainer, { target: { scrollTop: 240 } });
    expect(scrollContainer.scrollTop).toBe(240);

    rerender(<NodeDetailDrawer node={null} onClose={vi.fn()} />);
    rerender(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("node-detail-scroll").scrollTop).toBe(240);
    });
  });

  it("renders a delete button when onDelete is provided", () => {
    const node = { id: "n1", type: "idea", label: "测试节点", content: "" };
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onDelete={vi.fn()} />);

    expect(screen.getByTitle("删除节点")).toBeDefined();
  });

  it("does not render a delete button when onDelete is not provided", () => {
    const node = { id: "n1", type: "idea", label: "测试节点", content: "" };
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(screen.queryByTitle("删除节点")).toBeNull();
  });

  it("calls onDelete after user confirms", () => {
    const node = { id: "n1", type: "idea", label: "测试节点", content: "" };
    const onDelete = vi.fn();
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onDelete={onDelete} />);

    fireEvent.click(screen.getByTitle("删除节点"));

    expect(window.confirm).toHaveBeenCalled();
    expect(onDelete).toHaveBeenCalledWith(node);
  });

  it("does not call onDelete when user cancels confirmation", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const node = { id: "n1", type: "idea", label: "测试节点", content: "" };
    const onDelete = vi.fn();
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onDelete={onDelete} />);

    fireEvent.click(screen.getByTitle("删除节点"));

    expect(onDelete).not.toHaveBeenCalled();
  });

  it("enters edit mode and calls onUpdate with new title/content on save", async () => {
    const node = { id: "n1", type: "outline", label: "原标题", content: "原内容" };
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByTitle("编辑节点"));

    const titleInput = screen.getByDisplayValue("原标题");
    const contentArea = screen.getByDisplayValue("原内容");
    fireEvent.change(titleInput, { target: { value: "新标题" } });
    fireEvent.change(contentArea, { target: { value: "新内容" } });

    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith("n1", { title: "新标题", content: "新内容" });
    });
  });
});
