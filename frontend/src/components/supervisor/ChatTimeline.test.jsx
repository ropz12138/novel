import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChatTimeline } from "./ChatTimeline.jsx";

// ── Helpers ──

function renderTimeline(overrides = {}) {
  const props = {
    timeline: [],
    assistantDraft: "",
    assistantReasoningDraft: "",
    editDiff: null,
    outlineDiff: null,
    characterDiff: null,
    confirming: false,
    running: false,
    onToggleStep: vi.fn(),
    onConfirmEdit: vi.fn(),
    onConfirmOutline: vi.fn(),
    ...overrides,
  };
  return render(<ChatTimeline {...props} />);
}

// ── Tests ──

describe("ChatTimeline", () => {
  it("renders nothing when timeline is empty and no draft", () => {
    const { container } = renderTimeline();
    expect(container.innerHTML).toBe("");
  });

  // ── User messages ──

  it("renders user messages", () => {
    renderTimeline({
      timeline: [
        { kind: "message", id: 1, role: "user", content: "Hello AI", timestamp: Date.now() },
      ],
    });

    expect(screen.getByText("Hello AI")).toBeDefined();
  });

  it("preserves line breaks in user messages", () => {
    renderTimeline({
      timeline: [
        { kind: "message", id: 1, role: "user", content: "第一行\n第二行", timestamp: Date.now() },
      ],
    });

    const bubble = document.querySelector(".whitespace-pre-wrap");
    expect(bubble).toBeTruthy();
    expect(bubble.textContent).toBe("第一行\n第二行");
  });

  it("renders assistant messages with markdown", () => {
    renderTimeline({
      timeline: [
        { kind: "message", id: 1, role: "assistant", content: "**Bold text** and more", timestamp: Date.now() },
      ],
    });

    // Markdown should render <strong> for **Bold text**
    const bold = document.querySelector("strong");
    expect(bold).toBeDefined();
    expect(bold.textContent).toBe("Bold text");
  });

  // ── Error messages ──

  it("renders error messages with error styling", () => {
    renderTimeline({
      timeline: [
        { kind: "message", id: 1, role: "system", content: "Something failed", type: "error", timestamp: Date.now() },
      ],
    });

    expect(screen.getByText("Something failed")).toBeDefined();
  });

  // ── Execution steps ──

  it("renders running execution steps with spinner", () => {
    renderTimeline({
      timeline: [
        { kind: "step", id: 1, label: "thinking", status: "running", stream: "", panelOpen: false, timestamp: Date.now() },
      ],
    });

    expect(screen.getByText("thinking")).toBeDefined();
  });

  it("renders done execution steps with check icon", () => {
    renderTimeline({
      timeline: [
        { kind: "step", id: 1, label: "completed step", status: "done", stream: "some output", panelOpen: false, timestamp: Date.now() },
      ],
    });

    expect(screen.getByText("completed step")).toBeDefined();
  });

  it("shows stream content when panelOpen is true", () => {
    renderTimeline({
      timeline: [
        { kind: "step", id: 1, label: "step", status: "done", stream: "stream content here", panelOpen: true, timestamp: Date.now() },
      ],
    });

    expect(screen.getByText("stream content here")).toBeDefined();
  });

  it("renders step with reasoning stream before content stream", () => {
    renderTimeline({
      timeline: [
        {
          kind: "step",
          id: 1,
          label: "写第1章",
          status: "running",
          reasoningStream: "分析补丁",
          stream: '{"edits":',
          panelOpen: true,
          timestamp: Date.now(),
        },
      ],
      running: true,
    });

    const reasoning = screen.getByText("分析补丁");
    const content = screen.getByText('{"edits":');
    expect(reasoning.compareDocumentPosition(content) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("hides stream content when panelOpen is false", () => {
    renderTimeline({
      timeline: [
        { kind: "step", id: 1, label: "step", status: "done", stream: "hidden content", panelOpen: false, timestamp: Date.now() },
      ],
    });

    expect(screen.queryByText("hidden content")).toBeNull();
  });

  it("calls onToggleStep when clicking a step with stream content", () => {
    const onToggleStep = vi.fn();
    renderTimeline({
      timeline: [
        { kind: "step", id: 42, label: "clickable step", status: "done", stream: "content", panelOpen: false, timestamp: Date.now() },
      ],
      onToggleStep,
    });

    fireEvent.click(screen.getByText("clickable step"));
    expect(onToggleStep).toHaveBeenCalledWith(42);
  });

  // ── Diff cards ──

  it("renders edit_diff_card with accept/reject buttons when not readonly", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "assistant",
          content: "",
          type: "edit_diff_card",
          diffCard: {
            diff: [{ old: "a", new: "b" }],
            summary: { lines_added: 1, lines_removed: 1 },
            chapter_number: 3,
            readonly: false,
          },
          timestamp: Date.now(),
        },
      ],
    });

    expect(screen.getByText(/第3章修改建议/)).toBeDefined();
    expect(screen.getByText("接受修改")).toBeDefined();
    expect(screen.getByText("拒绝")).toBeDefined();
  });

  it("renders edit_diff_card without buttons when readonly", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "assistant",
          content: "",
          type: "edit_diff_card",
          diffCard: {
            diff: [],
            summary: { lines_added: 0, lines_removed: 0 },
            chapter_number: 1,
            readonly: true,
          },
          timestamp: Date.now(),
        },
      ],
    });

    expect(screen.getByText(/已自动应用/)).toBeDefined();
    expect(screen.queryByText("接受修改")).toBeNull();
  });

  it("renders patch_diff_card", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "assistant",
          content: "",
          type: "patch_diff_card",
          patchDiffCard: {
            hunks: [{
              type: "replace",
              removed: "old text",
              added: "new text",
              context_before: "",
              context_after: "",
              char_diff: [],
            }],
            summary: { applied: 2 },
          },
          timestamp: Date.now(),
        },
      ],
    });

    expect(screen.getByText(/章节局部修改/)).toBeDefined();
    expect(screen.getByText(/2 处改动/)).toBeDefined();
  });

  it("renders outline_diff_card", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "assistant",
          content: "",
          type: "outline_diff_card",
          outlineDiffCard: {
            diff: {},
            summary: { total_added: 2, total_modified: 1, total_removed: 0 },
            readonly: true,
          },
          timestamp: Date.now(),
        },
      ],
    });

    expect(screen.getByText(/大纲变更建议/)).toBeDefined();
  });

  it("renders character_diff_card", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "assistant",
          content: "",
          type: "character_diff_card",
          characterDiffCard: {
            diff: {},
            summary: { total_added: 1, total_modified: 0, total_removed: 0 },
            readonly: true,
          },
          timestamp: Date.now(),
        },
      ],
    });

    expect(screen.getByText(/角色变更建议/)).toBeDefined();
  });

  it("renders metadata_diff_card", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "assistant",
          content: "",
          type: "metadata_diff_card",
          metadataDiffCard: {
            chapter_number: 5,
            diff: {},
            diff_summary: { total_added: 1, total_modified: 0, total_removed: 0 },
          },
          timestamp: Date.now(),
        },
      ],
    });

    expect(screen.getByText(/第5章元数据变更/)).toBeDefined();
  });

  // ── assistantDraft (streaming) ──

  it("renders assistant draft as streaming message", () => {
    renderTimeline({
      assistantDraft: "streaming text...",
      running: true,
    });

    expect(screen.getByText("streaming text...")).toBeDefined();
  });

  it("renders reasoning draft with label and max-height container while thinking only", () => {
    renderTimeline({
      assistantReasoningDraft: "分析用户意图中...",
      assistantDraft: "",
      running: true,
    });

    expect(screen.getByText("思考过程")).toBeDefined();
    expect(screen.getByText("分析用户意图中...")).toBeDefined();
  });

  it("collapses reasoning draft once content draft starts streaming", () => {
    renderTimeline({
      assistantReasoningDraft: "思考中...",
      assistantDraft: "正式回复",
      running: true,
    });

    expect(screen.queryByText("思考过程")).toBeNull();
    expect(screen.queryByText("思考中...")).toBeNull();
    expect(screen.getByText("正式回复")).toBeDefined();
  });

  // ── Floating outline/character diff panel ──

  it("renders floating outline diff panel with confirm buttons", () => {
    renderTimeline({
      outlineDiff: {
        diff: {},
        summary: { total_added: 1, total_modified: 0, total_removed: 0 },
        message: "updated",
        operations: [],
        readonly: false,
      },
    });

    expect(screen.getByText("大纲变更建议")).toBeDefined();
    expect(screen.getByText("接受修改")).toBeDefined();
    expect(screen.getByText("拒绝")).toBeDefined();
  });

  it("renders floating outline diff panel as auto-applied when readonly", () => {
    renderTimeline({
      outlineDiff: {
        diff: {},
        summary: { total_added: 1, total_modified: 0, total_removed: 0 },
        message: "auto",
        operations: [],
        readonly: true,
      },
    });

    expect(screen.getByText(/已自动应用/)).toBeDefined();
  });

  it("renders floating character diff panel", () => {
    renderTimeline({
      characterDiff: {
        diff: {},
        summary: { total_added: 1, total_modified: 0, total_removed: 0 },
        readonly: false,
      },
    });

    expect(screen.getByText("角色变更建议")).toBeDefined();
  });

  // ── Confirm button actions ──

  it("calls onConfirmEdit when accept is clicked on edit_diff_card", () => {
    const onConfirmEdit = vi.fn();
    const diffCard = {
      diff: [{ old: "a", new: "b" }],
      summary: { lines_added: 1, lines_removed: 1 },
      chapter_number: 3,
      readonly: false,
    };

    renderTimeline({
      timeline: [
        { kind: "message", id: 1, role: "assistant", content: "", type: "edit_diff_card", diffCard, timestamp: Date.now() },
      ],
      onConfirmEdit,
    });

    fireEvent.click(screen.getByText("接受修改"));
    expect(onConfirmEdit).toHaveBeenCalledWith("accept", diffCard);
  });

  it("calls onConfirmEdit when reject is clicked on edit_diff_card", () => {
    const onConfirmEdit = vi.fn();
    const diffCard = {
      diff: [],
      summary: {},
      chapter_number: 1,
      readonly: false,
    };

    renderTimeline({
      timeline: [
        { kind: "message", id: 1, role: "assistant", content: "", type: "edit_diff_card", diffCard, timestamp: Date.now() },
      ],
      onConfirmEdit,
    });

    fireEvent.click(screen.getByText("拒绝"));
    expect(onConfirmEdit).toHaveBeenCalledWith("reject", diffCard);
  });

  it("calls onConfirmOutline when accept is clicked on floating outline diff", () => {
    const onConfirmOutline = vi.fn();
    renderTimeline({
      outlineDiff: {
        diff: {},
        summary: { total_added: 1, total_modified: 0, total_removed: 0 },
        message: "test",
        operations: [],
        readonly: false,
      },
      onConfirmOutline,
    });

    fireEvent.click(screen.getAllByText("接受修改")[0]);
    expect(onConfirmOutline).toHaveBeenCalledWith("accept");
  });
});
