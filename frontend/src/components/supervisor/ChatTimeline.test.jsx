import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatTimeline } from "./ChatTimeline.jsx";


function renderTimeline(overrides = {}) {
  return render(
    <ChatTimeline
      timeline={[]}
      assistantDraft=""
      assistantReasoningDraft=""
      running={false}
      onToggleStep={vi.fn()}
      {...overrides}
    />,
  );
}


describe("ChatTimeline", () => {
  it("renders nothing without messages, drafts, or a running request", () => {
    const { container } = renderTimeline();
    expect(container.innerHTML).toBe("");
  });

  it("renders user and assistant messages", () => {
    renderTimeline({
      timeline: [
        { kind: "message", id: 1, role: "user", content: "修改第一章" },
        { kind: "message", id: 2, role: "assistant", content: "**已完成**" },
      ],
    });

    expect(screen.getByText("修改第一章")).toBeDefined();
    expect(screen.getByText("已完成").tagName).toBe("STRONG");
  });

  it("hides assistant bubbles whose content is only ellipsis", () => {
    renderTimeline({
      timeline: [
        { kind: "message", id: 1, role: "user", content: "继续" },
        { kind: "message", id: 2, role: "assistant", content: "..." },
        { kind: "message", id: 3, role: "assistant", content: "已完成" },
      ],
      assistantDraft: "...",
    });

    expect(screen.getByText("继续")).toBeDefined();
    expect(screen.getByText("已完成")).toBeDefined();
    expect(screen.queryByText("...")).toBeNull();
  });

  it("renders context node markers as pills", () => {
    renderTimeline({
      timeline: [{
        kind: "message",
        id: 1,
        role: "user",
        content: "参考 [[ctx|node-1|character|林远]]",
      }],
    });

    expect(screen.getByText("林远")).toBeDefined();
  });

  it("renders and toggles a tool execution step", () => {
    const onToggleStep = vi.fn();
    renderTimeline({
      timeline: [{
        kind: "step",
        id: 1,
        label: "工具调用 · update_node",
        status: "done",
        panelOpen: false,
        stream: "执行完成",
      }],
      onToggleStep,
    });

    fireEvent.click(screen.getByText("工具调用 · update_node"));
    expect(onToggleStep).toHaveBeenCalledWith(1);
  });

  it("renders the active chapter content diff card", () => {
    renderTimeline({
      timeline: [{
        kind: "message",
        id: 1,
        role: "assistant",
        content: "",
        type: "chapter_content_diff_card",
        chapterContentDiffCard: {
          title: "第一章",
          hunks: [{
            type: "replace",
            paragraph_index: 1,
            old_text: "旧内容",
            new_text: "新内容",
          }],
          summary: { modified: 1 },
          word_count: 100,
          word_count_delta: 2,
        },
      }],
    });

    expect(screen.getByText("第一章")).toBeDefined();
    fireEvent.click(screen.getByText("替换"));
    expect(screen.getByText("旧内容")).toBeDefined();
    expect(screen.getByText("新内容")).toBeDefined();
  });

  it("allows a stored user message to be edited and resent", () => {
    const onEditMessage = vi.fn();
    renderTimeline({
      timeline: [{
        kind: "message",
        id: 1,
        role: "user",
        content: "原始内容",
        dbMessageId: "message-1",
      }],
      onEditMessage,
    });

    fireEvent.click(screen.getByLabelText("编辑并重新发送"));
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "修改后内容" },
    });
    fireEvent.click(screen.getByRole("button", { name: "重新发送" }));

    expect(onEditMessage).toHaveBeenCalledWith("message-1", "修改后内容");
  });

  it("does not allow a stored user actions message to be edited", () => {
    renderTimeline({
      timeline: [{
        kind: "message",
        id: 1,
        role: "user",
        content: "我修改了「第一章」节点。",
        type: "user_canvas_actions",
        meta: { type: "user_canvas_actions" },
        dbMessageId: "actions-1",
      }],
      onEditMessage: vi.fn(),
    });

    expect(screen.queryByLabelText("编辑并重新发送")).toBeNull();
  });

  it("renders streaming reasoning and answer content", () => {
    renderTimeline({
      assistantReasoningDraft: "正在分析",
      assistantDraft: "生成内容",
      running: true,
    });

    expect(screen.getByText("思考过程")).toBeDefined();
    expect(screen.getByText("生成内容")).toBeDefined();
  });
});
