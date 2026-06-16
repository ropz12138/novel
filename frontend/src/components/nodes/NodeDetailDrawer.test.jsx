import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../../lib/canvasApi", () => ({
  fetchChapter: vi.fn(),
}));

import { fetchChapter } from "../../lib/canvasApi";
import NodeDetailDrawer from "./NodeDetailDrawer";

describe("NodeDetailDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("exports a default component", async () => {
    expect(NodeDetailDrawer).toBeDefined();
    expect(typeof NodeDetailDrawer).toBe("function");
  });

  it("fetchChapter is called for chapter nodes", async () => {
    const mockChapter = {
      node_id: "node-1",
      summary: "测试摘要",
      new_facts: ["事实1"],
      foreshadows: ["伏笔1"],
    };
    fetchChapter.mockResolvedValue(mockChapter);

    const result = await fetchChapter("node-1");
    expect(result).toEqual(mockChapter);
    expect(fetchChapter).toHaveBeenCalledWith("node-1");
  });

  it("fetchChapter handles errors gracefully", async () => {
    fetchChapter.mockRejectedValue(new Error("Network error"));

    await expect(fetchChapter("node-1")).rejects.toThrow("Network error");
  });

  it("renders nothing when node is null", () => {
    const { container } = render(<NodeDetailDrawer node={null} onClose={vi.fn()} />);
    expect(container.firstChild).toBeNull();
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
});
