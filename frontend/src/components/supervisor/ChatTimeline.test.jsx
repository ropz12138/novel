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
  it("opens source references only when web navigation is supplied", () => {
    const onOpenNodeDetail = vi.fn();
    const content = `[查看原文](/node-reference?node_id=n1&quote=${encodeURIComponent("原文")})`;
    const props = { timeline: [{ kind: "message", id: 99, role: "assistant", content }] };
    const view = renderTimeline({ ...props, onOpenDiffNode: onOpenNodeDetail });
    fireEvent.click(screen.getByRole("button", { name: "查看原文" }));
    expect(onOpenNodeDetail).toHaveBeenCalledWith("n1", "原文");
    view.unmount();
    renderTimeline(props);
    expect(screen.queryByRole("link", { name: "查看原文" })).toBeNull();
    expect(screen.queryByRole("button", { name: "查看原文" })).toBeNull();
  });
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

  it("collapses user bubbles that exceed five lines and toggles expand/collapse", () => {
    const longContent = Array.from({ length: 8 }, (_, i) => `第${i + 1}行足够长的内容`).join("\n");
    const proto = HTMLElement.prototype;
    const scrollDesc = Object.getOwnPropertyDescriptor(proto, "scrollHeight");
    const clientDesc = Object.getOwnPropertyDescriptor(proto, "clientHeight");
    Object.defineProperty(proto, "scrollHeight", {
      configurable: true,
      get() {
        if (this.getAttribute?.("data-testid") === "user-message-body") {
          return this.classList.contains("line-clamp-5") ? 200 : 320;
        }
        return scrollDesc?.get?.call(this) ?? 0;
      },
    });
    Object.defineProperty(proto, "clientHeight", {
      configurable: true,
      get() {
        if (this.getAttribute?.("data-testid") === "user-message-body") {
          return this.classList.contains("line-clamp-5") ? 80 : 320;
        }
        return clientDesc?.get?.call(this) ?? 0;
      },
    });

    try {
      renderTimeline({
        timeline: [{ kind: "message", id: 1, role: "user", content: longContent }],
      });

      const body = screen.getByTestId("user-message-body");
      expect(body.className).toContain("line-clamp-5");
      fireEvent.click(screen.getByRole("button", { name: "展开" }));
      expect(body.className).not.toContain("line-clamp-5");
      fireEvent.click(screen.getByRole("button", { name: "收起" }));
      expect(body.className).toContain("line-clamp-5");
    } finally {
      if (scrollDesc) Object.defineProperty(proto, "scrollHeight", scrollDesc);
      else delete proto.scrollHeight;
      if (clientDesc) Object.defineProperty(proto, "clientHeight", clientDesc);
      else delete proto.clientHeight;
    }
  });

  it("does not show expand on short user bubbles", () => {
    renderTimeline({
      timeline: [{ kind: "message", id: 1, role: "user", content: "短消息" }],
    });
    expect(screen.queryByRole("button", { name: "展开" })).toBeNull();
  });

  it("hides quoted node text from user bubbles but keeps the following instruction", () => {
    renderTimeline({
      timeline: [{
        kind: "message",
        id: 1,
        role: "user",
        content: "[[ctx|node-1|plot|废墟相遇]]\n“废墟中遇见苏婉”\n请强化这一处伏笔",
      }],
    });

    expect(screen.getByText("废墟相遇")).toBeDefined();
    expect(screen.queryByText("废墟中遇见苏婉")).toBeNull();
    expect(screen.getByText(/请强化这一处伏笔/)).toBeDefined();
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
    expect(screen.queryByText("旧内容")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    fireEvent.click(screen.getByText("替换"));
    expect(screen.getByTestId("inline-diff-new").textContent).toBe("新内容");
    expect(screen.queryByTestId("inline-diff-old")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "对照" }));
    expect(screen.getByTestId("inline-diff-old").textContent).toBe("旧内容");
    expect(screen.getByTestId("inline-diff-new").textContent).toBe("新内容");
    fireEvent.click(screen.getByRole("button", { name: "收起" }));
    expect(screen.queryByText("旧内容")).toBeNull();
  });

  it("opens the corresponding node when a diff bubble is clicked", () => {
    const onOpenDiffNode = vi.fn();
    renderTimeline({
      onOpenDiffNode,
      timeline: [{
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
      }],
    });

    fireEvent.click(screen.getByRole("button", { name: "打开节点详情：第一章" }));
    expect(onOpenDiffNode).toHaveBeenCalledWith("chapter-1");
  });

  it("expands a diff without opening its node", () => {
    const onOpenDiffNode = vi.fn();
    renderTimeline({
      onOpenDiffNode,
      timeline: [{
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
      }],
    });

    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(onOpenDiffNode).not.toHaveBeenCalled();
  });

  it("loads diff hunks only after expanding a summary card", () => {
    const onExpandDiff = vi.fn();
    renderTimeline({
      onExpandDiff,
      timeline: [{
        kind: "message",
        id: 1,
        role: "assistant",
        content: "",
        dbMessageId: "diff-1",
        type: "chapter_content_diff_card",
        chapterContentDiffCard: {
          title: "第二章",
          node_type: "chapter",
          summary: { paragraphs_changed: 2 },
          word_count: 80,
        },
      }],
    });

    expect(screen.getByText("第二章")).toBeDefined();
    expect(screen.getByText("2 处修改")).toBeDefined();
    expect(screen.getByText("共 80 字")).toBeDefined();
    expect(screen.queryByText("替换")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "展开" }));
    expect(onExpandDiff).toHaveBeenCalledWith("diff-1");
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

  it("caps a running tool step content stream at the reasoning max height", () => {
    renderTimeline({
      timeline: [{
        kind: "step",
        id: 1,
        label: "工具调用 · write_chapter_draft",
        status: "running",
        panelOpen: true,
        reasoningStream: "先看原文",
        stream: "很长的专职模型正文",
      }],
    });

    const content = screen.getByText("很长的专职模型正文");
    expect(content.className).toContain("max-h-48");
    expect(content.className).toContain("overflow-y-auto");
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
