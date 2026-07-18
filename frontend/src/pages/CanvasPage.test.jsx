import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const apiMocks = vi.hoisted(() => ({
  fetchWorks: vi.fn(),
  createWork: vi.fn(),
  deleteWork: vi.fn(),
}));

vi.mock("../lib/canvasApi", () => ({
  fetchWorks: apiMocks.fetchWorks,
  createWork: apiMocks.createWork,
  deleteWork: apiMocks.deleteWork,
}));

vi.mock("../components/Canvas", () => ({
  default: () => <div data-testid="canvas-mock" />,
}));

vi.mock("../components/AgentChat", () => ({
  default: () => <div data-testid="agent-chat-mock" />,
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
  });

  it("shows delete button in work selector and calls deleteWork", async () => {
    render(
      <MemoryRouter>
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

  it("lets the user drag the chat panel wider", async () => {
    render(
      <MemoryRouter>
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
});
