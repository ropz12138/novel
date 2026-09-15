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
});
