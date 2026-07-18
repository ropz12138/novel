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

  it("shows edit button when user message has dbMessageId", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "user",
          content: "Hello AI",
          dbMessageId: "msg-1",
          timestamp: Date.now(),
        },
      ],
      onEditMessage: vi.fn(),
    });

    expect(screen.getByLabelText("编辑并重新发送")).toBeDefined();
  });

  it("hides edit button when dbMessageId is missing or agent is running", () => {
    renderTimeline({
      timeline: [
        { kind: "message", id: 1, role: "user", content: "Hello AI", timestamp: Date.now() },
      ],
      onEditMessage: vi.fn(),
    });
    expect(screen.queryByLabelText("编辑并重新发送")).toBeNull();

    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 2,
          role: "user",
          content: "Hello AI",
          dbMessageId: "msg-2",
          timestamp: Date.now(),
        },
      ],
      onEditMessage: vi.fn(),
      running: true,
    });
    expect(screen.queryByLabelText("编辑并重新发送")).toBeNull();
  });

  it("enters edit mode and can cancel via button, close icon, or Escape", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "user",
          content: "原始内容",
          dbMessageId: "msg-1",
          timestamp: Date.now(),
        },
      ],
      onEditMessage: vi.fn(),
    });

    fireEvent.click(screen.getByLabelText("编辑并重新发送"));
    expect(screen.getByText("编辑消息")).toBeDefined();
    const textarea = screen.getByRole("textbox");
    expect(textarea.value).toBe("原始内容");

    fireEvent.change(textarea, { target: { value: "修改后" } });
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByText("编辑消息")).toBeNull();
    expect(screen.getByText("原始内容")).toBeDefined();

    fireEvent.click(screen.getByLabelText("编辑并重新发送"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "修改后" } });
    fireEvent.click(screen.getByLabelText("取消编辑"));
    expect(screen.queryByText("编辑消息")).toBeNull();
    expect(screen.getByText("原始内容")).toBeDefined();

    fireEvent.click(screen.getByLabelText("编辑并重新发送"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "修改后" } });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByText("编辑消息")).toBeNull();
    expect(screen.getByText("原始内容")).toBeDefined();
  });

  it("calls onEditMessage when resend is clicked in edit mode", () => {
    const onEditMessage = vi.fn();
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "user",
          content: "原始内容",
          dbMessageId: "msg-1",
          timestamp: Date.now(),
        },
      ],
      onEditMessage,
    });

    fireEvent.click(screen.getByLabelText("编辑并重新发送"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "  新内容  " } });
    fireEvent.click(screen.getByRole("button", { name: "重新发送" }));

    expect(onEditMessage).toHaveBeenCalledWith("msg-1", "  新内容  ");
    expect(screen.queryByText("编辑消息")).toBeNull();
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

  it("renders failed execution steps with X icon", () => {
    renderTimeline({
      timeline: [
        { kind: "step", id: 1, label: "工具调用 · bad_tool", status: "failed", stream: "", panelOpen: false, timestamp: Date.now() },
      ],
    });

    expect(screen.getByText("工具调用 · bad_tool")).toBeDefined();
    const icon = document.querySelector(".text-red-400");
    expect(icon).toBeTruthy();
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

    expect(screen.getByText("思考过程")).toBeDefined();
    expect(screen.queryByText("分析补丁")).toBeNull();
    expect(screen.getByText('{"edits":')).toBeDefined();
  });

  it("shows reasoning stream expanded when content has not started", () => {
    renderTimeline({
      timeline: [
        {
          kind: "step",
          id: 1,
          label: "写第1章",
          status: "running",
          reasoningStream: "分析补丁",
          stream: "",
          panelOpen: true,
          timestamp: Date.now(),
        },
      ],
      running: true,
    });

    expect(screen.getByText("分析补丁")).toBeDefined();
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

  it("renders chapter_content_diff_card", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "assistant",
          content: "",
          type: "chapter_content_diff_card",
          chapterContentDiffCard: {
            title: "第2章",
            hunks: [{
              type: "replace",
              paragraph_index: 2,
              old_text: "旧段落",
              new_text: "新段落",
            }],
            summary: { paragraphs_changed: 1, chars_added: 3, chars_removed: 3 },
            word_count: 200,
            word_count_delta: 0,
          },
          timestamp: Date.now(),
        },
      ],
    });

    expect(screen.getByText("第2章")).toBeDefined();
    expect(screen.getByText(/1 处修改/)).toBeDefined();
    expect(screen.getByText(/已自动应用并保存/)).toBeDefined();
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

  it("collapses reasoning draft when content draft streams", () => {
    renderTimeline({
      assistantReasoningDraft: "思考中...",
      assistantDraft: "正式回复",
      running: true,
    });

    expect(screen.getByText("思考过程")).toBeDefined();
    expect(screen.queryByText("思考中...")).toBeNull();
    expect(screen.getByText("正式回复")).toBeDefined();
  });

  it("expands collapsed reasoning draft on click", () => {
    renderTimeline({
      assistantReasoningDraft: "思考中...",
      assistantDraft: "正式回复",
      running: true,
    });

    fireEvent.click(screen.getByText("思考过程"));
    expect(screen.getByText("思考中...")).toBeDefined();
  });

  it("history message reasoning collapsed by default", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "assistant",
          content: "回复正文",
          reasoningContent: "历史思考内容",
          timestamp: Date.now(),
        },
      ],
    });

    expect(screen.getByText("思考过程")).toBeDefined();
    expect(screen.queryByText("历史思考内容")).toBeNull();
    expect(screen.getByText("回复正文")).toBeDefined();
  });

  it("history message reasoning expands on click", () => {
    renderTimeline({
      timeline: [
        {
          kind: "message",
          id: 1,
          role: "assistant",
          content: "回复正文",
          reasoningContent: "历史思考内容",
          timestamp: Date.now(),
        },
      ],
    });

    fireEvent.click(screen.getByText("思考过程"));
    expect(screen.getByText("历史思考内容")).toBeDefined();
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
