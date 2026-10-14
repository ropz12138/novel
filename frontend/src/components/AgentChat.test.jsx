import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentChat, { latestStreamLine, scrollTopAfterPrepend } from "./AgentChat";
import { getChapterReviewIntensity, putChapterReviewIntensity } from "../lib/canvasApi";
import { sessionApi } from "../lib/api";

const mocks = vi.hoisted(() => ({
  handleSend: vi.fn(),
  handleStop: vi.fn(),
  running: false,
  timeline: [],
}));

vi.mock("../hooks/useSupervisorChat", () => ({
  useSupervisorChat: () => ({
    timeline: mocks.timeline,
    input: "",
    running: mocks.running,
    sessionId: mocks.running ? "session-1" : null,
    assistantDraft: "",
    assistantReasoningDraft: "",
    handleSend: mocks.handleSend,
    handleStop: mocks.handleStop,
    handleSelectSession: vi.fn(),
    resetState: vi.fn(),
    toggleStepPanel: vi.fn(),
    handleEditResend: vi.fn(),
  }),
}));

vi.mock("../hooks/useSmartScroll", () => ({
  useSmartScroll: () => ({ stickToBottom: true, scrollToBottom: vi.fn() }),
}));

vi.mock("../lib/canvasApi", () => ({
  getChapterReviewIntensity: vi.fn().mockResolvedValue({ chapter_review_intensity: "medium" }),
  putChapterReviewIntensity: vi.fn().mockResolvedValue({ chapter_review_intensity: "medium" }),
}));

vi.mock("../lib/api", () => ({
  sessionApi: {
    listSupervisor: vi.fn().mockResolvedValue([]),
    deleteSupervisor: vi.fn(),
  },
}));

vi.mock("../lib/keyboardInset", () => ({
  useKeyboardInset: () => 300,
}));

describe("AgentChat context quote", () => {
  it("shows persisted context usage in the desktop session list", async () => {
    sessionApi.listSupervisor.mockResolvedValueOnce([
      { id: "s1", title: "第一章", context_input_tokens: 12345 },
      { id: "s2", title: "第二章", context_input_tokens: 0 },
    ]);
    render(<AgentChat workId="work-1" />);
    await waitFor(() => expect(sessionApi.listSupervisor).toHaveBeenCalledWith("work-1"));
    fireEvent.click(screen.getByRole("button", { name: /新对话/ }));
    expect(await screen.findByText("【12,345】 tokens")).toBeDefined();
    expect(screen.getAllByText("【0】 tokens").length).toBeGreaterThan(0);
  });
  it("does not send on Enter", () => {
    render(<AgentChat workId="work-1" appMode />);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "创作指令" }), { key: "Enter" });
    expect(mocks.handleSend).not.toHaveBeenCalled();
  });
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.running = false;
    mocks.timeline = [];
    vi.stubGlobal("PointerEvent", MouseEvent);
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
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "创作指令" }));
    caretNode.textContent += "请强化这一处伏笔";

    await waitFor(() => expect(screen.getByRole("button", { name: "发送" }).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(mocks.handleSend).toHaveBeenCalledWith(
      "[[ctx|node-1|plot|废墟相遇]]\n“废墟中遇见苏婉”\n请强化这一处伏笔",
      "medium",
    );
    await waitFor(() => expect(screen.getByText("AI 写作助手")).toBeDefined());
  });

  it("focuses the composer after quoting a node without selected text", () => {
    const insertPillRef = createRef();
    render(<AgentChat workId="work-1" insertPillRef={insertPillRef} />);
    screen.getByRole("button", { name: "发送" }).focus();
    expect(document.activeElement).not.toBe(screen.getByRole("textbox", { name: "创作指令" }));

    act(() => {
      insertPillRef.current("node-1", "chapter", "第一章");
    });

    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "创作指令" }));
  });

  it("lifts the sidebar composer above the App keyboard", () => {
    render(<AgentChat workId="work-1" />);

    expect(screen.getByTestId("agent-chat").style.paddingBottom).toBe("300px");
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

  it("defaults chapter review intensity to medium and snaps by sliding, not clicking", async () => {
    render(<AgentChat workId="work-1" />);
    expect(screen.queryByText("按 Enter 发送，Shift + Enter 换行")).toBeNull();

    const slider = screen.getByRole("slider", { name: "章节评审强度" });
    expect(slider.getAttribute("aria-valuetext")).toBe("medium");
    expect(slider.querySelector("[data-intensity-window]").getAttribute("data-intensity")).toBe("medium");

    fireEvent.click(screen.getByText("高"));
    expect(slider.getAttribute("aria-valuetext")).toBe("medium");

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
    fireEvent.pointerMove(slider, { clientX: 80, pointerId: 1 });
    fireEvent.pointerUp(slider, { clientX: 80, pointerId: 1 });
    expect(slider.getAttribute("aria-valuetext")).toBe("high");
    expect(slider.querySelector("[data-intensity-window]").getAttribute("data-intensity")).toBe("high");
    await waitFor(() => expect(putChapterReviewIntensity).toHaveBeenCalledWith({
      chapter_review_intensity: "high",
    }));

    const editable = screen.getByRole("textbox", { name: "创作指令" });
    editable.textContent = "写第七章";
    fireEvent.input(editable);
    await waitFor(() => expect(screen.getByRole("button", { name: "发送" }).disabled).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(mocks.handleSend).toHaveBeenCalledWith("写第七章", "high");
  });

  it("exposes shared App composer actions and the latest stream line", async () => {
    const ref = createRef();
    const onStateChange = vi.fn();
    render(<AgentChat ref={ref} workId="work-1" onStateChange={onStateChange} />);

    await waitFor(() => expect(ref.current.ready).toBe(true));
    await waitFor(() => expect(getChapterReviewIntensity).toHaveBeenCalled());
    await act(async () => {});
    act(() => ref.current.send("从最新会话继续写"));
    expect(mocks.handleSend).toHaveBeenCalledWith("从最新会话继续写", "medium");

    act(() => ref.current.newSession());
    expect(onStateChange).toHaveBeenCalled();
    expect(typeof ref.current.selectSession).toBe("function");
  });

  it("opens a diff node from the Web conversation", () => {
    const onOpenNodeDetail = vi.fn();
    mocks.timeline = [{
      kind: "message",
      id: 1,
      role: "assistant",
      content: "",
      type: "chapter_content_diff_card",
      chapterContentDiffCard: {
        node_id: "chapter-1",
        title: "第一章",
        hunks: [],
        summary: { paragraphs_changed: 1 },
      },
    }];

    render(<AgentChat workId="work-1" onOpenNodeDetail={onOpenNodeDetail} />);
    fireEvent.click(screen.getByRole("button", { name: "打开节点详情：第一章" }));
    expect(onOpenNodeDetail).toHaveBeenCalledWith("chapter-1");
  });

  it("does not make diff bubbles open nodes in App mode", () => {
    mocks.timeline = [{
      kind: "message",
      id: 1,
      role: "assistant",
      content: "",
      type: "chapter_content_diff_card",
      chapterContentDiffCard: {
        node_id: "chapter-1",
        title: "第一章",
        hunks: [],
        summary: { paragraphs_changed: 1 },
      },
    }];

    render(<AgentChat appMode workId="work-1" onOpenNodeDetail={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "打开节点详情：第一章" })).toBeNull();
  });

  it("shares chapter review intensity with the App composer", async () => {
    const ref = createRef();
    const onStateChange = vi.fn();
    render(<AgentChat ref={ref} workId="work-1" onStateChange={onStateChange} />);

    await waitFor(() => expect(ref.current.ready).toBe(true));
    expect(onStateChange).toHaveBeenCalledWith(expect.objectContaining({ chapterReviewIntensity: "medium" }));

    act(() => ref.current.setIntensity("high"));
    expect(screen.getByRole("slider", { name: "章节评审强度" }).getAttribute("aria-valuetext")).toBe("high");
    expect(onStateChange).toHaveBeenCalledWith(expect.objectContaining({ chapterReviewIntensity: "high" }));
    await waitFor(() => expect(putChapterReviewIntensity).toHaveBeenCalledWith({
      chapter_review_intensity: "high",
    }));
  });

  it("restores the saved chapter review intensity", async () => {
    getChapterReviewIntensity.mockResolvedValueOnce({ chapter_review_intensity: "low" });
    render(<AgentChat workId="work-1" />);
    await waitFor(() => {
      expect(screen.getByRole("slider", { name: "章节评审强度" }).getAttribute("aria-valuetext")).toBe("low");
    });
  });

  it("exposes stop on the shared App composer handle", () => {
    mocks.running = true;
    const ref = createRef();
    render(<AgentChat ref={ref} workId="work-1" />);

    act(() => ref.current.stop());
    expect(mocks.handleStop).toHaveBeenCalledOnce();
  });

  it("closes the session dropdown when clicking outside", async () => {
    render(<AgentChat workId="work-1" />);
    await waitFor(() => expect(screen.getByText("新对话")).toBeDefined());

    fireEvent.click(screen.getByText("新对话"));
    expect(screen.getByText("暂无对话")).toBeDefined();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByText("暂无对话")).toBeNull();
  });

  it("submits to the backend immediately while running instead of keeping a local queue", async () => {
    mocks.running = true;
    const { rerender } = render(<AgentChat workId="work-1" />);
    const input = screen.getByRole("textbox", { name: "创作指令" });
    await act(async () => {});
    input.textContent = "接着处理第二项";
    fireEvent.input(input);
    fireEvent.click(screen.getByLabelText("发送"));
    expect(mocks.handleSend).toHaveBeenCalledWith("接着处理第二项", "medium");

    mocks.running = false;
    rerender(<AgentChat workId="work-1" />);
    await waitFor(() => expect(mocks.handleSend).toHaveBeenCalledWith("接着处理第二项", "medium"));
    expect(mocks.handleSend).toHaveBeenCalledOnce();
  });

  it("captures modification capsules in the queued user message", async () => {
    mocks.running = true;
    const onModifiedNodesSent = vi.fn();
    const { rerender } = render(<AgentChat workId="work-1"
      modifiedNodes={[{ id: "n1", type: "chapter", label: "第一章" }]}
      onModifiedNodesSent={onModifiedNodesSent} />);
    const input = screen.getByRole("textbox", { name: "创作指令" });
    await waitFor(() => expect(getChapterReviewIntensity).toHaveBeenCalled());
    await act(async () => {});
    input.textContent = "继续";
    fireEvent.input(input);
    fireEvent.click(screen.getByLabelText("发送"));
    expect(onModifiedNodesSent).toHaveBeenCalledOnce();
    mocks.running = false;
    rerender(<AgentChat workId="work-1" modifiedNodes={[]} />);
    await waitFor(() => expect(mocks.handleSend).toHaveBeenCalledWith(
      "[[ctx|n1|chapter|已修改：第一章]]\n继续", "medium",
    ));
  });

  it("uses the single composer button to stop when running with empty input", () => {
    mocks.running = true;
    render(<AgentChat workId="work-1" />);
    expect(screen.queryByLabelText("发送")).toBeNull();
    fireEvent.click(screen.getByLabelText("中止"));
    expect(mocks.handleStop).toHaveBeenCalledOnce();
  });

});

describe("scrollTopAfterPrepend", () => {
  it("keeps the same messages in view after older history is inserted", () => {
    expect(scrollTopAfterPrepend(12, 400, 650)).toBe(262);
  });
});

describe("latestStreamLine", () => {
  it("keeps only the last non-empty line of the active stream", () => {
    expect(latestStreamLine({
      timeline: [],
      assistantDraft: "第一行\n第二行\n",
      assistantReasoningDraft: "",
      running: true,
    })).toBe("第二行");
  });
});
