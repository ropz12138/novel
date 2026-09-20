import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentChat from "./AgentChat";

const mocks = vi.hoisted(() => ({
  handleSend: vi.fn(),
}));

vi.mock("../hooks/useSupervisorChat", () => ({
  useSupervisorChat: () => ({
    timeline: [],
    input: "",
    running: false,
    sessionId: null,
    assistantDraft: "",
    assistantReasoningDraft: "",
    handleSend: mocks.handleSend,
    handleSelectSession: vi.fn(),
    resetState: vi.fn(),
    toggleStepPanel: vi.fn(),
    handleEditResend: vi.fn(),
  }),
}));

vi.mock("../hooks/useSmartScroll", () => ({
  useSmartScroll: () => ({ stickToBottom: true, scrollToBottom: vi.fn() }),
}));

vi.mock("../lib/api", () => ({
  sessionApi: {
    listSupervisor: vi.fn().mockResolvedValue([]),
    deleteSupervisor: vi.fn(),
  },
}));

describe("AgentChat context quote", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows selected node text and includes it in the sent message", async () => {
    const insertPillRef = createRef();
    render(<AgentChat workId="work-1" insertPillRef={insertPillRef} />);

    act(() => {
      insertPillRef.current("node-1", "plot", "废墟相遇", "废墟中遇见苏婉");
    });

    expect(screen.getByText("废墟相遇")).toBeDefined();
    expect(screen.getByText("废墟中遇见苏婉")).toBeDefined();
    expect(screen.getByTitle("选中的节点原文").getAttribute("data-context-quote"))
      .toBe("废墟中遇见苏婉");

    const quote = screen.getByTitle("选中的节点原文");
    const editable = quote.parentElement;
    const caretNode = editable.lastChild;
    expect(caretNode.nodeType).toBe(Node.TEXT_NODE);
    expect(caretNode.textContent).toBe("\u200B");
    caretNode.textContent += "请强化这一处伏笔";

    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(mocks.handleSend).toHaveBeenCalledWith(
      "[[ctx|node-1|plot|废墟相遇]]\n“废墟中遇见苏婉”\n请强化这一处伏笔",
      "low",
    );
    await waitFor(() => expect(screen.getByText("AI 写作助手")).toBeDefined());
  });

  it("removes the context pill and its quote together", () => {
    const insertPillRef = createRef();
    render(<AgentChat workId="work-1" insertPillRef={insertPillRef} />);

    act(() => {
      insertPillRef.current("node-1", "plot", "废墟相遇", "废墟中遇见苏婉");
    });
    fireEvent.click(screen.getByRole("button", { name: "移除上下文 废墟相遇" }));

    expect(screen.queryByText("废墟相遇")).toBeNull();
    expect(screen.queryByText("废墟中遇见苏婉")).toBeNull();
    expect(screen.getByRole("button", { name: "发送" }).disabled).toBe(true);
  });

  it("defaults chapter review intensity to low and snaps by sliding, not clicking", () => {
    render(<AgentChat workId="work-1" />);
    expect(screen.queryByText("按 Enter 发送，Shift + Enter 换行")).toBeNull();

    const slider = screen.getByRole("slider", { name: "章节评审强度" });
    expect(slider.getAttribute("aria-valuetext")).toBe("low");
    expect(slider.querySelector("[data-intensity-window]").getAttribute("data-intensity")).toBe("low");

    fireEvent.click(screen.getByText("中"));
    expect(slider.getAttribute("aria-valuetext")).toBe("low");

    vi.spyOn(slider, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 90,
      bottom: 20,
      width: 90,
      height: 20,
      toJSON: () => ({}),
    });
    fireEvent.pointerDown(slider, { clientX: 5, pointerId: 1 });
    fireEvent.pointerMove(slider, { clientX: 45, pointerId: 1 });
    fireEvent.pointerUp(slider, { clientX: 45, pointerId: 1 });
    expect(slider.getAttribute("aria-valuetext")).toBe("medium");
    expect(slider.querySelector("[data-intensity-window]").getAttribute("data-intensity")).toBe("medium");

    const editable = screen.getByRole("textbox", { name: "创作指令" });
    editable.textContent = "写第七章";
    fireEvent.input(editable);
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(mocks.handleSend).toHaveBeenCalledWith("写第七章", "medium");
  });
});
