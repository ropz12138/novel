import { forwardRef } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const apiMocks = vi.hoisted(() => ({
  fetchWorks: vi.fn(),
  createWork: vi.fn(),
  deleteWork: vi.fn(),
  fetchContentDiffs: vi.fn(),
}));

vi.mock("../lib/canvasApi", () => ({
  fetchWorks: apiMocks.fetchWorks,
  createWork: apiMocks.createWork,
  deleteWork: apiMocks.deleteWork,
  fetchContentDiffs: apiMocks.fetchContentDiffs,
}));

vi.mock("../components/Canvas", () => ({
  default: forwardRef(function CanvasMock({ workId, nodeContentDiffs }, _ref) {
    return <div data-testid="canvas-mock" data-work-id={workId}
      data-diff-count={Object.keys(nodeContentDiffs).length} />;
  }),
}));

vi.mock("../components/AgentChat", () => ({
  default: ({ onNodeContentDiff, onCollapse }) => <div data-testid="agent-chat-mock">
    <button aria-label="收起Agent侧边栏" onClick={onCollapse}>收起Agent侧边栏</button>
    <button onClick={() => onNodeContentDiff?.("chapter-live", {
      original_content: "旧正文", current_content: "新正文",
      hunks: [{ type: "replace", paragraph_index: 1, old_text: "旧正文", new_text: "新正文" }],
    })}>模拟实时正文修改</button>
  </div>,
}));

vi.mock("../components/ModelConfigDialog", () => ({
  default: () => null,
}));

import { CanvasPage } from "./CanvasPage";

describe("CanvasPage delete work", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.stubGlobal("confirm", vi.fn(() => true));
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 1280,
    });
    apiMocks.fetchWorks.mockResolvedValue({
      works: [
        { id: "w1", title: "作品一", created_at: "2026-01-01T00:00:00Z" },
        { id: "w2", title: "作品二", created_at: "2026-01-02T00:00:00Z" },
      ],
    });
    apiMocks.deleteWork.mockResolvedValue(undefined);
    apiMocks.fetchContentDiffs.mockResolvedValue([]);
  });

  it("shows delete button in work selector and calls deleteWork", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );

    await screen.findByText("作品一");

    fireEvent.click(screen.getByText("作品:"));

    const deleteButtons = await screen.findAllByTitle("删除作品");
    expect(deleteButtons.length).toBe(2);

    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      expect(apiMocks.deleteWork).toHaveBeenCalledWith("w1");
    });
  });

  it("restores the last active work after a page refresh", async () => {
    window.localStorage.setItem("novel_canvas_last_active_work", "w2");

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );

    const canvas = await screen.findByTestId("canvas-mock");
    expect(canvas.dataset.workId).toBe("w2");
    expect(screen.getByText("作品二")).toBeDefined();
  });

  it("restores pending agent body diffs from the server", async () => {
    apiMocks.fetchContentDiffs.mockResolvedValue([{
      node_id: "chapter-1", original_content: "旧正文", current_content: "新正文",
    }]);
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByTestId("canvas-mock").dataset.diffCount).toBe("1"));
  });

  it("shows an agent body diff as soon as the live event arrives", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );
    await screen.findByTestId("canvas-mock");
    fireEvent.click(screen.getByRole("button", { name: "模拟实时正文修改" }));
    await waitFor(() => expect(screen.getByTestId("canvas-mock").dataset.diffCount).toBe("1"));
  });

  it("lets the user drag the chat panel wider", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );

    await screen.findByTestId("agent-chat-mock");

    const separator = screen.getByRole("separator", { name: "调整对话区域宽度" });
    const panel = separator.parentElement;
    const initialWidth = Number.parseInt(panel.style.width, 10);
    expect(initialWidth).toBeGreaterThanOrEqual(340);

    fireEvent.mouseDown(separator, { button: 0, clientX: 900 });
    fireEvent.mouseMove(window, { clientX: 780 });
    fireEvent.mouseUp(window);

    const expectedWidth = initialWidth + 120;
    await waitFor(() => {
      expect(panel.style.width).toBe(`${expectedWidth}px`);
      expect(window.localStorage.getItem("novel_canvas_chat_width")).toBe(String(expectedWidth));
    });
  });

  it("expands and collapses Agent from controls in the sidebar", async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CanvasPage />
      </MemoryRouter>,
    );

    await screen.findByTestId("agent-chat-mock");
    expect(screen.queryByText("隐藏Agent")).toBeNull();
    expect(screen.queryByText("显示Agent")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "收起Agent侧边栏" }));
    expect(screen.queryByTestId("agent-chat-mock")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "展开Agent侧边栏" }));
    expect(await screen.findByTestId("agent-chat-mock")).toBeDefined();
  });
});
