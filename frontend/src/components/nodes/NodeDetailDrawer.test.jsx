import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { decideAgentGroup } from "../../lib/agentContentDiff";
import NodeDetailDrawer from "./NodeDetailDrawer";

vi.mock("../../lib/agentContentDiff", async () => {
  const actual = await vi.importActual("../../lib/agentContentDiff");
  return {
    ...actual,
    decideAgentGroup: vi.fn((...args) => actual.decideAgentGroup(...args)),
  };
});

describe("NodeDetailDrawer", () => {
  it("opens chapter notes and scrolls to the expanded change rather than the identical body text", async () => {
    const scroll = vi.fn();
    const previous = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = scroll;
    try {
      render(<NodeDetailDrawer node={{ id: "diff-location", type: "chapter", label: "章节",
        content: "相同的新内容", notes: "开头笔记\n\n相同的新内容",
        diffTarget: { field: "notes", hunk: { paragraph_index: 2, new_text: "相同的新内容", old_text: "旧笔记" } },
      }} onClose={vi.fn()} />);
      await waitFor(() => expect(scroll).toHaveBeenCalled());
      expect(screen.getByText("章节笔记").closest("details").open).toBe(true);
      expect(screen.getByTestId("chapter-notes").querySelector("[data-diff-navigation-hit]")?.textContent).toBe("相同的新内容");
      expect(screen.getByTestId("chapter-body").querySelector("[data-diff-navigation-hit]")).toBeNull();
      const hit = screen.getByTestId("chapter-notes").querySelector("[data-diff-navigation-hit]");
      expect(scroll.mock.instances).toContain(hit);
      expect(hit.className).not.toMatch(/bg-amber-100|ring-amber-300|ring-1/);
    } finally { Element.prototype.scrollIntoView = previous; }
  });

  it("locates a deleted paragraph at its remaining position and relocates when another change is opened", async () => {
    const previous = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = vi.fn();
    const base = { id: "deleted-location", type: "chapter", label: "章节", content: "开头\n\n后续段落\n\n结尾" };
    try {
      const { container, rerender } = render(<NodeDetailDrawer node={{ ...base, diffTarget: {
        field: "content", hunk: { type: "delete", paragraph_index: 2, old_text: "已删除的段落", new_text: "" },
      } }} onClose={vi.fn()} />);
      await waitFor(() => expect(container.querySelector("[data-diff-navigation-hit]")?.textContent).toBe("后续段落"));
      rerender(<NodeDetailDrawer node={{ ...base, diffTarget: {
        field: "content", hunk: { type: "replace", paragraph_index: 3, new_text: "结尾" },
      } }} onClose={vi.fn()} />);
      await waitFor(() => expect(container.querySelector("[data-diff-navigation-hit]")?.textContent).toBe("结尾"));
      expect(container.querySelectorAll("[data-diff-navigation-hit]")).toHaveLength(1);
      expect(container.querySelector("[data-diff-navigation-hit]").className).not.toMatch(/bg-amber-100|ring-amber-300|ring-1/);
    } finally { Element.prototype.scrollIntoView = previous; }
  });

  it.each([false, true])("edits ordinary chapter text after opening a source reference, pending diff=%s", async (pending) => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const onDecision = vi.fn().mockResolvedValue(undefined);
    const current = "首段新文。\n\n这里有普通正文。";
    render(<NodeDetailDrawer node={{ id: "reference-edit", type: "chapter", label: "章节", content: current,
      sourceReference: "这里有普通正文。" }}
      contentDiff={pending ? { original_content: "首段旧文。\n\n这里有普通正文。", current_content: current,
        hunks: [{ type: "replace", paragraph_index: 1, old_text: "首段旧文。", new_text: "首段新文。" }] } : undefined}
      onUpdate={onUpdate} onContentDiffDecision={onDecision} onClose={vi.fn()} />);
    expect(screen.getByText("这里有普通正文。").closest("[data-node-reference-hit]")).toBeTruthy();
    fireEvent.click(screen.getByText("这里有普通正文。"));
    const editor = screen.getByRole("textbox", { name: "编辑段落内容" });
    expect(editor.value).toBe("这里有普通正文。");
    fireEvent.change(editor, { target: { value: "这里是手动修改后的正文。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存段落" }));
    await waitFor(() => expect(pending ? onDecision : onUpdate).toHaveBeenCalled());
    if (pending) {
      expect(onDecision).toHaveBeenCalledWith("reference-edit", expect.objectContaining({
        current_content: "首段新文。\n\n这里是手动修改后的正文。",
      }));
    } else {
      expect(onUpdate).toHaveBeenCalledWith("reference-edit", {
        content: "首段新文。\n\n这里是手动修改后的正文。", expected_content: current,
      });
    }
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "编辑段落内容" })).toBeNull());
  });

  it("highlights a paragraph-range reference while the chapter still has a pending diff", () => {
    const current = "甲新。\n\n乙原文。";
    const unchangedStart = current.indexOf("乙原文。");
    const changedStart = current.indexOf("甲新。");
    const { container, rerender } = render(<NodeDetailDrawer node={{
      id: "diff-range-ref", type: "chapter", label: "章节", content: current,
      sourceReference: { start: unchangedStart, end: unchangedStart + "乙原文。".length, part: "content" },
    }} contentDiff={{
      original_content: "甲旧。\n\n乙原文。", current_content: current,
      hunks: [{ type: "replace", paragraph_index: 1, old_text: "甲旧。", new_text: "甲新。" }],
    }} onContentDiffDecision={vi.fn()} onClose={vi.fn()} />);
    const unchanged = container.querySelector("[data-testid=chapter-body] [data-node-reference-hit]");
    expect(unchanged?.textContent).toContain("乙原文。");
    expect(unchanged?.textContent).not.toContain("甲新。");

    rerender(<NodeDetailDrawer node={{
      id: "diff-range-ref", type: "chapter", label: "章节", content: current,
      sourceReference: { start: changedStart, end: changedStart + "甲新。".length, part: "content" },
    }} contentDiff={{
      original_content: "甲旧。\n\n乙原文。", current_content: current,
      hunks: [{ type: "replace", paragraph_index: 1, old_text: "甲旧。", new_text: "甲新。" }],
    }} onContentDiffDecision={vi.fn()} onClose={vi.fn()} />);
    const changed = container.querySelector("[data-testid=chapter-body] [data-node-reference-hit]");
    expect(changed?.textContent).toContain("甲新。");
    expect(changed?.textContent).not.toContain("乙原文。");
  });

  it("highlights a body reference in the chapter text and leaves the notes alone", () => {
    const notes = "xxxxxx装备清单";
    const content = "yyyyyy借着悬空";
    const { container } = render(<NodeDetailDrawer node={{
      id: "split-ref", type: "chapter", label: "章节", content, notes,
      sourceReference: { start: 6, end: 10, part: "content" },
    }} onClose={vi.fn()} />);
    expect(container.querySelector("[data-testid=chapter-notes] [data-node-reference-hit]")).toBeNull();
    expect(container.querySelector("[data-testid=chapter-body] [data-node-reference-hit]")?.textContent).toContain("借着悬空");
  });

  it("highlights a notes reference in the notes and leaves the body alone", () => {
    const notes = "xxxxxx装备清单";
    const content = "yyyyyy借着悬空";
    const { container } = render(<NodeDetailDrawer node={{
      id: "notes-ref", type: "chapter", label: "章节", content, notes,
      sourceReference: { start: 6, end: 10, part: "notes" },
    }} onClose={vi.fn()} />);
    expect(container.querySelector("[data-testid=chapter-body] [data-node-reference-hit]")).toBeNull();
    expect(container.querySelector("[data-testid=chapter-notes] [data-node-reference-hit]")?.textContent).toContain("装备清单");
  });

  it("highlights the numbered paragraph even when the same text appears twice", () => {
    const content = "甲。\n\n甲。";
    const { container } = render(<NodeDetailDrawer node={{ id: "ref-span", type: "chapter", label: "章节", content, sourceReference: { start: 4, end: 6 } }} onClose={vi.fn()} />);
    const hits = container.querySelectorAll("[data-node-reference-hit]");
    expect(hits).toHaveLength(1);
    expect(hits[0].textContent).toContain("甲。");
    expect(container.textContent.indexOf("甲。")).toBeLessThan(container.textContent.lastIndexOf("甲。"));
  });

  it("highlights one markdown list item from the source range", () => {
    const content = "# 情节一\n\n- 甲\n- 乙";
    const start = content.lastIndexOf("- 乙");
    const { container } = render(<NodeDetailDrawer node={{
      id: "plot-ref", type: "plot", label: "情节", content,
      sourceReference: { start, end: start + "- 乙".length, part: "content" },
    }} onUpdate={vi.fn()} onClose={vi.fn()} />);
    const hit = container.querySelector("[data-node-reference-hit]");
    expect(hit?.textContent).toContain("乙");
    expect(hit?.textContent).not.toContain("甲");
  });

  it("locates a repeated list change by source offset and can reject only that item", async () => {
    const old = "- 同样\n- 同样";
    const current = "- 同样\n- 改后";
    const start = old.indexOf("\n") + 1;
    const onDecision = vi.fn().mockResolvedValue(undefined);
    const { container } = render(<NodeDetailDrawer node={{
      id: "plot-dup", type: "plot", label: "情节", content: current,
      diffTarget: { field: "content", hunk: { type: "replace", start_offset: start, paragraph_index: 2, old_text: "- 同样", new_text: "- 改后" } },
    }} contentDiff={{
      grouping: "agent_replacements", original_content: old, current_content: current,
      hunks: [{ type: "replace", start_offset: start, paragraph_index: 2, old_text: "- 同样", new_text: "- 改后" }],
    }} onContentDiffDecision={onDecision} onContentDiffChange={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(container.querySelector("[data-diff-navigation-hit]")?.textContent).toContain("改后"));
    fireEvent.click(screen.getByRole("button", { name: "撤回修改" }));
    await waitFor(() => expect(onDecision).toHaveBeenCalledWith("plot-dup", expect.objectContaining({
      current_content: old,
      groups: [],
    })));
  });

  it("highlights a referenced plain-text paragraph without parsing Markdown syntax", () => {
    const { container } = render(<NodeDetailDrawer node={{ id: "ref", type: "chapter", label: "章节", content: "前文\n\n这里有**重要**线索。", sourceReference: "这里有**重要**线索。" }} onClose={vi.fn()} />);
    expect(container.querySelector("[data-node-reference-hit]")?.textContent).toBe("这里有**重要**线索。");
  });
  it("navigates non-chapter nodes across levels on web", () => {
    const navigationNodes = [
      { id: "volume-1", type: "volume", label: "第一卷" },
      { id: "volume-2", type: "volume", label: "第二卷" },
      { id: "plot-1", type: "plot", label: "第一个情节" },
    ];
    const onChapterNavigate = vi.fn();
    render(<NodeDetailDrawer node={navigationNodes[1]} onClose={vi.fn()}
      navigationNodes={navigationNodes} onChapterNavigate={onChapterNavigate} />);
    fireEvent.click(screen.getByTitle("上一节点"));
    expect(onChapterNavigate).toHaveBeenCalledWith(navigationNodes[0]);
    fireEvent.click(screen.getByTitle("下一节点"));
    expect(onChapterNavigate).toHaveBeenCalledWith(navigationNodes[2]);
  });

  it("navigates non-chapter nodes with swipes in app mode", () => {
    const navigationNodes = [
      { id: "plot-1", type: "plot", label: "情节一" },
      { id: "plot-2", type: "plot", label: "情节二" },
    ];
    const onChapterNavigate = vi.fn();
    render(<NodeDetailDrawer appMode node={navigationNodes[0]} onClose={vi.fn()}
      navigationNodes={navigationNodes} onChapterNavigate={onChapterNavigate} />);
    const scroller = screen.getByTestId("node-detail-scroll");
    fireEvent.touchStart(scroller, { touches: [{ clientX: 240, clientY: 120 }] });
    fireEvent.touchEnd(scroller, { changedTouches: [{ clientX: 120, clientY: 126 }] });
    expect(onChapterNavigate).toHaveBeenCalledWith(navigationNodes[1]);
  });
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("exports a default component", () => {
    expect(NodeDetailDrawer).toBeDefined();
    expect(typeof NodeDetailDrawer).toBe("function");
  });

  it("reports when node editing starts and ends", async () => {
    const onEditingChange = vi.fn();
    render(
      <NodeDetailDrawer
        node={{ id: "edit-state", type: "plot", label: "情节点", content: "" }}
        onClose={vi.fn()}
        onUpdate={vi.fn()}
        onEditingChange={onEditingChange}
      />,
    );

    await waitFor(() => expect(onEditingChange).toHaveBeenLastCalledWith(false));
    fireEvent.click(screen.getByTitle("编辑全文"));
    await waitFor(() => expect(onEditingChange).toHaveBeenLastCalledWith(true));
    fireEvent.click(screen.getByText("取消"));
    await waitFor(() => expect(onEditingChange).toHaveBeenLastCalledWith(false));
  });

  it("reports inline paragraph editing so App mode can hide its composer", async () => {
    const onEditingChange = vi.fn();
    render(
      <NodeDetailDrawer
        appMode
        node={{ id: "inline-edit-state", type: "chapter", label: "第一章", content: "正文。", extra_data: {} }}
        onClose={vi.fn()}
        onUpdate={vi.fn()}
        onEditingChange={onEditingChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "编辑段落" }));
    await waitFor(() => expect(onEditingChange).toHaveBeenLastCalledWith(true));
    fireEvent.click(screen.getByText("取消"));
    await waitFor(() => expect(onEditingChange).toHaveBeenLastCalledWith(false));
  });

  it.each([false, true])("keeps one inline editor and closes it outside, appMode=%s", (appMode) => {
    render(
      <NodeDetailDrawer
        appMode={appMode}
        node={{ id: "single-inline-editor", type: "chapter", label: "第一章", content: "第一段。\n\n第二段。", extra_data: {} }}
        onClose={vi.fn()}
        onUpdate={vi.fn()}
      />,
    );

    const paragraphs = screen.getAllByRole("button", { name: "编辑段落" });
    fireEvent.click(paragraphs[0]);
    expect(screen.getAllByRole("textbox", { name: "编辑段落内容" })).toHaveLength(1);

    fireEvent.pointerDown(paragraphs[1]);
    fireEvent.click(paragraphs[1]);
    expect(screen.getAllByRole("textbox", { name: "编辑段落内容" })).toHaveLength(1);
    expect(screen.getByRole("textbox", { name: "编辑段落内容" }).value).toBe("第二段。");

    fireEvent.pointerDown(screen.getByTestId("chapter-detail-header"));
    expect(screen.queryByRole("textbox", { name: "编辑段落内容" })).toBeNull();
  });

  it("renders chapter content and latest sync result from node data", () => {
    const node = {
      id: "node-1",
      type: "chapter",
      label: "第一章",
      content: "林川进入档案室。",
      extra_data: {
        last_generation: {
          sync_evaluations: [
            {
              passed: true,
              plan_alignment: {
                completed: ["林川进入档案室", "顾岚阻止林川"],
                missing: [],
              },
            },
          ],
        },
      },
    };

    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(screen.getByText("林川进入档案室。")).toBeDefined();
    expect(screen.getByText("与画布规划同步")).toBeDefined();
    expect(screen.getByText("林川进入档案室", { exact: true })).toBeDefined();
    expect(screen.getByText("顾岚阻止林川")).toBeDefined();
    expect(screen.getByText("自动修订 0 次")).toBeDefined();
  });

  it("copies the complete original chapter content", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const content = "第一段。\n\n[[PLOT]]完整情节标记[[/PLOT]]\n\n第三段。";
    render(
      <NodeDetailDrawer
        node={{ id: "copy-chapter", type: "chapter", label: "第一章", content, extra_data: {} }}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "复制正文" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(content));
    expect(screen.getByRole("button", { name: "正文已复制" })).toBeDefined();
  });

  it("renders dedicated plot highlights in chapter node content", () => {
    const node = {
      id: "node-1",
      type: "chapter",
      label: "第一章",
      content: "开场状态。[[PLOT]]林川进入档案室，并找到了失踪人员名单。[[/PLOT]]后续正文。",
      extra_data: {},
    };

    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    const highlighted = screen.getByText("林川进入档案室，并找到了失踪人员名单。");
    expect(highlighted).toBeDefined();
    expect(highlighted.className).toContain("bg-amber-100");
    expect(screen.queryByText("[[PLOT]]林川进入档案室，并找到了失踪人员名单。[[/PLOT]]")).toBeNull();
    expect(document.querySelector("strong")).toBeNull();
  });

  it("renders chapter body as plain text without interpreting HTML tags", () => {
    const { container } = render(
      <NodeDetailDrawer
        node={{
          id: "node-br",
          type: "chapter",
          label: "换行章节",
          content: "第一行<br>第二行<br />第三行",
          extra_data: {},
        }}
        onClose={vi.fn()}
      />,
    );

    expect(container.querySelectorAll("br")).toHaveLength(0);
    expect(container.textContent).toContain("第一行<br>第二行<br />第三行");
  });

  it("does not parse Markdown tables in chapter body", () => {
    const { container } = render(
      <NodeDetailDrawer
        node={{
          id: "node-table-br",
          type: "chapter",
          label: "表格章节",
          content: "| 阶层 | 人物 |\n| --- | --- |\n| 顶层<br>暴力集团 | 王猛<br>韩烈 |",
          extra_data: {},
        }}
        onClose={vi.fn()}
      />,
    );

    expect(container.querySelector("table")).toBeNull();
    expect(container.textContent).toContain("| 阶层 | 人物 |");
    expect(container.textContent).toContain("顶层<br>暴力集团");
  });

  it("keeps Markdown syntax literal in chapter body", () => {
    const { container } = render(
      <NodeDetailDrawer
        node={{
          id: "chapter-plain-text",
          type: "chapter",
          label: "纯文本章节",
          content: "**不是粗体**\n\n# 不是标题",
          extra_data: {},
        }}
        onClose={vi.fn()}
      />,
    );

    const body = screen.getByTestId("chapter-body");
    expect(body.textContent).toContain("**不是粗体**");
    expect(body.textContent).toContain("# 不是标题");
    expect(container.querySelector("strong")).toBeNull();
    expect(body.querySelector("h1")).toBeNull();
  });

  it("renders chapter elements at the top of chapter detail", () => {
    const node = {
      id: "node-1",
      type: "chapter",
      label: "第一章",
      content: "正文",
      extra_data: {
        chapter_elements: [
          { id: "e1", title: "主角觉醒", content: "林远第一次感知时间异常" },
          { id: "e2", title: "仓库逃亡", content: "从仓库侧门逃出" },
        ],
      },
    };

    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(screen.getByText("本章元素")).toBeDefined();
    expect(screen.getByText("2 项")).toBeDefined();
    expect(screen.getByText("主角觉醒")).toBeDefined();
    expect(screen.getByText("仓库逃亡")).toBeDefined();
  });

  it("renders chapter character names without exposing character ids", () => {
    const node = {
      id: "node-1",
      type: "chapter",
      label: "第一章",
      content: "正文",
      extra_data: {
        characters: [
          { id: "char-uuid-1", name: "林川" },
          { id: "char-uuid-2", name: "苏婉" },
        ],
      },
    };

    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(screen.getByText("出场角色")).toBeDefined();
    expect(screen.getByText("2 人")).toBeDefined();
    expect(screen.getByText("林川")).toBeDefined();
    expect(screen.getByText("苏婉")).toBeDefined();
    expect(screen.queryByText("char-uuid-1")).toBeNull();
  });

  it("keeps a visible character highlight while cycling only through chapter prose", () => {
    const highlights = new Map();
    vi.stubGlobal("CSS", { highlights });
    vi.stubGlobal("Highlight", class extends Set { constructor(...ranges) { super(ranges); } });
    const { unmount, container } = render(
      <NodeDetailDrawer
        node={{
          id: "chapter-character-navigation",
          type: "chapter",
          label: "第一章",
          content: "林川看见林川。",
          notes: "林川的章节笔记",
          extra_data: { characters: [{ id: "char-1", name: "林川" }] },
        }}
        onClose={vi.fn()}
      />,
    );

    const characterButton = screen.getByRole("button", { name: "定位角色：林川" });
    const offsets = [];
    for (let index = 0; index < 3; index += 1) {
      fireEvent.click(characterButton);
      expect(highlights.size).toBe(1);
      const [range] = [...highlights.values()][0];
      expect(screen.getByTestId("chapter-prose").contains(range.startContainer)).toBe(true);
      expect(range.toString()).toBe("林川");
      offsets.push(range.startOffset);
      window.getSelection().removeAllRanges();
      expect(highlights.size).toBe(1);
    }
    expect(offsets).toEqual([0, 4, 0]);
    expect(container.querySelector("style").textContent).toContain("::highlight(");
    unmount();
    expect(highlights.size).toBe(0);
    vi.unstubAllGlobals();
  });

  it("clears character navigation highlights when the chapter changes", () => {
    const highlights = new Map();
    vi.stubGlobal("CSS", { highlights });
    vi.stubGlobal("Highlight", class extends Set { constructor(...ranges) { super(ranges); } });
    const node = { id: "one", type: "chapter", label: "第一章", content: "林川。", extra_data: { characters: [{ name: "林川" }] } };
    const { rerender, unmount } = render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);
    const characterButton = screen.getByRole("button", { name: "定位角色：林川" });
    fireEvent.click(characterButton);
    expect(highlights.size).toBe(1);
    rerender(<NodeDetailDrawer node={{ ...node, id: "two", content: "第二章的林川。" }} onClose={vi.fn()} />);
    expect(highlights.size).toBe(0);
    unmount();
    vi.unstubAllGlobals();
  });

  it("keeps chapter metadata in a left-aligned header outside the body scroller", () => {
    const node = {
      id: "node-header",
      type: "chapter",
      label: "第十二章：雨夜来客",
      content: "正文内容",
      extra_data: {
        characters: [{ id: "char-1", name: "林川" }],
        chapter_elements: [{ id: "element-1", title: "雨夜敲门", content: "推进情节" }],
      },
    };

    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    const header = screen.getByTestId("chapter-detail-header");
    const scroller = screen.getByTestId("node-detail-scroll");
    expect(header.className).toContain("text-left");
    expect(scroller.contains(header)).toBe(false);
    expect(header.contains(screen.getByText("第十二章：雨夜来客"))).toBe(true);
    expect(header.contains(screen.getByText("4 字"))).toBe(true);
    expect(header.contains(screen.getByText("出场角色"))).toBe(true);
    expect(header.contains(screen.getByText("本章元素"))).toBe(true);
  });

  it("keeps Markdown double-star syntax as ordinary bold text", () => {
    const node = {
      id: "node-1",
      type: "character",
      label: "林川",
      content: "人物核心：**谨慎、克制，但会冒险。**",
      extra_data: {},
    };

    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    const boldText = screen.getByText("谨慎、克制，但会冒险。");
    expect(boldText.tagName).toBe("STRONG");
    expect(boldText.className).not.toContain("bg-amber-100");
  });

  it("quotes diff prose without toolbar labels and deletion markers", () => {
    const node = { id: "quote-diff", type: "chapter", label: "章节", content: "雨夜来客。", extra_data: {} };
    const onAddContext = vi.fn();
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onAddContext={onAddContext}
      contentDiff={{ hunks: [{ type: "replace", paragraph_index: 1, old_text: "雨夜旧门来客。", new_text: "雨夜来客。" }] }} />);
    const hunk = screen.getByTestId("inline-diff-hunk");
    const range = document.createRange();
    range.selectNodeContents(hunk);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    fireEvent.mouseUp(screen.getByTestId("node-detail-scroll"));
    fireEvent.click(screen.getByRole("button", { name: "引用此段" }));
    expect(onAddContext).toHaveBeenCalledWith(node, "雨夜来客。");
  });

  it("shows 引用此段 after selecting text and adds that quote to conversation context", () => {
    const node = {
      id: "plot-1",
      type: "plot",
      label: "废墟相遇",
      content: "林川在废墟中遇见苏婉。",
      extra_data: {},
    };
    const onAddContext = vi.fn();
    render(
      <NodeDetailDrawer
        node={node}
        onClose={vi.fn()}
        onAddContext={onAddContext}
      />,
    );

    const selectedNode = screen.getByText("林川在废墟中遇见苏婉。").firstChild;
    vi.spyOn(window, "getSelection").mockReturnValue({
      rangeCount: 1,
      getRangeAt: () => ({ commonAncestorContainer: selectedNode, cloneContents: () => {
        const fragment = document.createDocumentFragment();
        fragment.append(document.createTextNode("废墟中遇见苏婉"));
        return fragment;
      } }),
      toString: () => "废墟中遇见苏婉",
    });

    fireEvent.mouseUp(screen.getByTestId("node-detail-scroll"));
    fireEvent.click(screen.getByRole("button", { name: "引用此段" }));

    expect(onAddContext).toHaveBeenCalledWith(node, "废墟中遇见苏婉");
    expect(screen.queryByRole("button", { name: "引用此段" })).toBeNull();
  });

  it("shows 引用此段 after a mobile selectionchange in app chapter details", () => {
    const node = {
      id: "chapter-quote",
      type: "chapter",
      label: "第一章",
      content: "雨夜来客敲开了旧门。",
      extra_data: {},
    };
    const onAddContext = vi.fn();
    render(
      <NodeDetailDrawer
        appMode
        node={node}
        onClose={vi.fn()}
        onAddContext={onAddContext}
      />,
    );

    const selectedNode = screen.getByText("雨夜来客敲开了旧门。").firstChild;
    vi.spyOn(window, "getSelection").mockReturnValue({
      rangeCount: 1,
      getRangeAt: () => ({
        commonAncestorContainer: selectedNode,
        cloneContents: () => {
          const fragment = document.createDocumentFragment();
          fragment.append(document.createTextNode("雨夜来客"));
          return fragment;
        },
        getBoundingClientRect: () => ({ left: 40, right: 180, top: 120, bottom: 148, width: 140, height: 28 }),
      }),
      toString: () => "雨夜来客",
    });

    fireEvent(document, new Event("selectionchange"));
    fireEvent.click(screen.getByRole("button", { name: "引用此段" }));

    expect(onAddContext).toHaveBeenCalledWith(node, "雨夜来客");
  });

  it("does not rebuild the rendered content when text selection is captured", () => {
    const node = {
      id: "plot-1",
      type: "plot",
      label: "废墟相遇",
      content: "林川在废墟中遇见苏婉。",
      extra_data: {},
    };
    render(
      <NodeDetailDrawer
        node={node}
        onClose={vi.fn()}
        onAddContext={vi.fn()}
      />,
    );

    const contentBeforeSelection = screen.getByText("林川在废墟中遇见苏婉。");
    const selectedNode = contentBeforeSelection.firstChild;
    vi.spyOn(window, "getSelection").mockReturnValue({
      rangeCount: 1,
      getRangeAt: () => ({ commonAncestorContainer: selectedNode, cloneContents: () => {
        const fragment = document.createDocumentFragment();
        fragment.append(document.createTextNode("废墟中遇见苏婉"));
        return fragment;
      } }),
      toString: () => "废墟中遇见苏婉",
    });

    fireEvent.mouseUp(screen.getByTestId("node-detail-scroll"));

    expect(screen.getByText("林川在废墟中遇见苏婉。")).toBe(contentBeforeSelection);
    expect(screen.getByRole("button", { name: "引用此段" })).toBeDefined();
  });

  it("does not show the old whole-node context button in node details", () => {
    render(
      <NodeDetailDrawer
        node={{ id: "plot-1", type: "plot", label: "废墟相遇", content: "正文", extra_data: {} }}
        onClose={vi.fn()}
        onAddContext={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "加入对话上下文" })).toBeNull();
  });

  it("stacks compact chapter metadata under the word count in App mode", () => {
    const node = {
      id: "node-app-header",
      type: "chapter",
      label: "第十二章：雨夜来客",
      content: "正文内容",
      extra_data: {
        characters: [{ id: "char-1", name: "林川" }],
        chapter_elements: [{ id: "element-1", title: "雨夜敲门", content: "推进情节" }],
      },
    };

    render(<NodeDetailDrawer appMode node={node} onClose={vi.fn()} />);

    const header = screen.getByTestId("chapter-detail-header");
    const title = screen.getByText("第十二章：雨夜来客");
    const wordCount = screen.getByText("4 字");

    expect(title.className).toContain("text-sm");
    expect(wordCount.className).toContain("text-[10px]");
    expect(title.compareDocumentPosition(wordCount) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("出场角色")).toBeNull();
    expect(header.contains(screen.getByRole("button", { name: "展开详情" }))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "展开详情" }));
    expect(screen.getByText("出场角色")).toBeDefined();
    expect(title.parentElement.contains(screen.getByRole("button", { name: "收起详情" }))).toBe(true);
    expect(wordCount.compareDocumentPosition(screen.getByText("出场角色")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("出场角色").compareDocumentPosition(screen.getByText("本章元素")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("collapses chapter characters and elements together in App mode", () => {
    render(
      <NodeDetailDrawer
        appMode
        node={{
          id: "node-app-collapse",
          type: "chapter",
          label: "第一章",
          content: "正文",
          extra_data: {
            characters: [{ id: "char-1", name: "林川" }],
            chapter_elements: [{ id: "element-1", title: "雨夜敲门", content: "推进情节" }],
          },
        }}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "展开详情" }));
    expect(screen.getByText("林川")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "收起详情" }));

    expect(screen.queryByText("林川")).toBeNull();
    expect(screen.queryByText("雨夜敲门")).toBeNull();
    expect(screen.getByRole("button", { name: "展开详情" })).toBeDefined();
  });

  it("opens node details fullscreen without a fullscreen toggle in App mode", () => {
    render(
      <NodeDetailDrawer
        appMode
        node={{ id: "plot-1", type: "plot", label: "废墟相遇", content: "正文", extra_data: {} }}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByTestId("node-detail-drawer").className).toContain("w-full");
    expect(screen.queryByRole("button", { name: "全屏查看" })).toBeNull();
    expect(screen.queryByRole("button", { name: "退出全屏" })).toBeNull();
  });

  it("shows agent content diffs inline in the body with apply and revert actions", async () => {
    const node = {
      id: "plot-1",
      type: "plot",
      label: "废墟相遇",
      content: "开场。\n\n林川在雨中遇见苏婉。",
      extra_data: {},
    };
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    const onContentDiffChange = vi.fn();
    render(
      <NodeDetailDrawer
        node={node}
        contentDiff={{
          hunks: [{
            type: "replace",
            paragraph_index: 2,
            old_text: "林川在废墟中遇见苏婉。",
            new_text: "林川在雨中遇见苏婉。",
          }],
          summary: { paragraphs_changed: 1, chars_added: 1, chars_removed: 2 },
        }}
        onClose={vi.fn()}
        onUpdate={onUpdate}
        onContentDiffDecision={onContentDiffDecision}
        onContentDiffChange={onContentDiffChange}
      />,
    );

    expect(screen.queryByRole("button", { name: "更改 1" })).toBeNull();
    expect(screen.queryByTestId("node-content-diff")).toBeNull();
    expect(screen.getByRole("button", { name: "全部保留" })).toBeDefined();
    expect(screen.getByRole("button", { name: "全部撤回" })).toBeDefined();
    expect(screen.getByText("开场。")).toBeDefined();
    expect(screen.getByTestId("inline-diff-hunk")).toBeDefined();
    expect(screen.queryByTestId("inline-diff-old")).toBeNull();
    expect(screen.getByTestId("inline-diff-new").textContent).toBe("林川在雨中遇见苏婉。");
    fireEvent.click(screen.getByRole("button", { name: "对照" }));
    expect(screen.getByTestId("inline-diff-old").textContent).toContain("废墟");

    fireEvent.click(screen.getByRole("button", { name: "保留修改" }));
    await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledWith("plot-1", expect.objectContaining({
      baseline_content: "开场。\n\n林川在雨中遇见苏婉。",
      current_content: "开场。\n\n林川在雨中遇见苏婉。",
    })));
    expect(onUpdate).not.toHaveBeenCalled();
    expect(onContentDiffChange).toHaveBeenCalledWith(null);
  });

  it("undoes and redoes one applied diff operation with Ctrl+Z and Ctrl+Y", async () => {
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    render(
      <NodeDetailDrawer
        node={{ id: "diff-history", type: "chapter", label: "第一章", content: "这一段新正文。", extra_data: {} }}
        contentDiff={{
          original_content: "这一段旧正文。",
          current_content: "这一段新正文。",
          hunks: [{ type: "replace", paragraph_index: 1, old_text: "这一段旧正文。", new_text: "这一段新正文。" }],
        }}
        onClose={vi.fn()}
        onContentDiffDecision={onContentDiffDecision}
        onContentDiffChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "保留修改" }));
    await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledTimes(1));

    fireEvent.keyDown(document, { key: "z", ctrlKey: true });
    await waitFor(() => expect(onContentDiffDecision).toHaveBeenNthCalledWith(2, "diff-history", {
      expected_content: "这一段新正文。",
      expected_baseline: "这一段新正文。",
      baseline_content: "这一段旧正文。",
      current_content: "这一段新正文。",
    }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    fireEvent.keyDown(document, { key: "y", ctrlKey: true });
    await waitFor(() => expect(onContentDiffDecision).toHaveBeenNthCalledWith(3, "diff-history", {
      expected_content: "这一段新正文。",
      expected_baseline: "这一段旧正文。",
      baseline_content: "这一段新正文。",
      current_content: "这一段新正文。",
    }));
  });

  it("treats cancelling a diff as one undoable operation", async () => {
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    render(
      <NodeDetailDrawer
        node={{ id: "reject-history", type: "chapter", label: "第一章", content: "这一段新正文。", extra_data: {} }}
        contentDiff={{
          original_content: "这一段旧正文。",
          current_content: "这一段新正文。",
          hunks: [{ type: "replace", paragraph_index: 1, old_text: "这一段旧正文。", new_text: "这一段新正文。" }],
        }}
        onClose={vi.fn()}
        onContentDiffDecision={onContentDiffDecision}
        onContentDiffChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "撤回修改" }));
    await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledTimes(1));
    fireEvent.keyDown(document, { key: "z", ctrlKey: true });

    await waitFor(() => expect(onContentDiffDecision).toHaveBeenNthCalledWith(2, "reject-history", {
      expected_content: "这一段旧正文。",
      expected_baseline: "这一段旧正文。",
      baseline_content: "这一段旧正文。",
      current_content: "这一段新正文。",
    }));
  });

  it("edits an ordinary paragraph in place without leaving reading mode", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(
      <NodeDetailDrawer
        node={{ id: "chapter-inline", type: "chapter", label: "第一章", content: "第一段。\n\n第二段。", extra_data: {} }}
        onClose={vi.fn()}
        onUpdate={onUpdate}
      />,
    );

    fireEvent.click(screen.getAllByRole("button", { name: "编辑段落" })[1]);
    const editor = screen.getByRole("textbox", { name: "编辑段落内容" });
    fireEvent.change(editor, { target: { value: "第二段改。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存段落" }));

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith("chapter-inline", {
      content: "第一段。\n\n第二段改。",
      expected_content: "第一段。\n\n第二段。",
    }));
    expect(screen.queryByText("编辑节点")).toBeNull();
  });

  it("undoes and redoes one saved paragraph operation with Ctrl+Z and Ctrl+Y", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(
      <NodeDetailDrawer
        node={{ id: "chapter-history", type: "chapter", label: "第一章", content: "原段落。", extra_data: {} }}
        onClose={vi.fn()}
        onUpdate={onUpdate}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "编辑段落" }));
    fireEvent.change(screen.getByRole("textbox", { name: "编辑段落内容" }), { target: { value: "新段落。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存段落" }));
    await waitFor(() => expect(onUpdate).toHaveBeenCalledTimes(1));

    fireEvent.keyDown(document, { key: "z", ctrlKey: true });
    await waitFor(() => expect(onUpdate).toHaveBeenNthCalledWith(2, "chapter-history", {
      content: "原段落。",
      expected_content: "新段落。",
    }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    fireEvent.keyDown(document, { key: "y", ctrlKey: true });
    await waitFor(() => expect(onUpdate).toHaveBeenNthCalledWith(3, "chapter-history", {
      content: "新段落。",
      expected_content: "原段落。",
    }));
  });

  it("commits a user edit without adding it to an existing agent diff", async () => {
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    render(
      <NodeDetailDrawer
        node={{ id: "user-edit-with-diff", type: "chapter", label: "第一章", content: "Agent新段。\n\n用户原文。", extra_data: {} }}
        contentDiff={{
          original_content: "Agent旧段。\n\n用户原文。",
          current_content: "Agent新段。\n\n用户原文。",
          hunks: [{ type: "replace", paragraph_index: 1, old_text: "Agent旧段。", new_text: "Agent新段。" }],
        }}
        onClose={vi.fn()}
        onUpdate={vi.fn()}
        onContentDiffDecision={onContentDiffDecision}
        onContentDiffChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "编辑段落" }));
    fireEvent.change(screen.getByRole("textbox", { name: "编辑段落内容" }), { target: { value: "用户手改。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存段落" }));

    await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledWith("user-edit-with-diff", expect.objectContaining({
      baseline_content: "Agent旧段。\n\n用户手改。",
      current_content: "Agent新段。\n\n用户手改。",
    })));
  });

  it("edits only the new side of a pending diff in place", async () => {
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    const onContentDiffChange = vi.fn();
    render(
      <NodeDetailDrawer
        node={{ id: "plot-inline", type: "plot", label: "相遇", content: "林川在雨中。", extra_data: {} }}
        contentDiff={{
          original_content: "林川在废墟中。",
          current_content: "林川在雨中。",
          hunks: [{ type: "replace", paragraph_index: 1, old_text: "林川在废墟中。", new_text: "林川在雨中。" }],
        }}
        onClose={vi.fn()}
        onUpdate={vi.fn()}
        onContentDiffDecision={onContentDiffDecision}
        onContentDiffChange={onContentDiffChange}
      />,
    );

    expect(screen.queryByRole("button", { name: "编辑原文" })).toBeNull();
    expect(screen.queryByRole("button", { name: "编辑新文" })).toBeNull();
    fireEvent.click(screen.getByTestId("inline-diff-new"));
    const editor = screen.getByRole("textbox", { name: "编辑新文内容" });
    expect(screen.queryByRole("button", { name: "查看替换前文本" })).toBeNull();
    expect(screen.queryByText("已删除一段 · 点击查看")).toBeNull();
    fireEvent.change(editor, { target: { value: "林川在细雨中。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存新文" }));

    await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledWith("plot-inline", {
      expected_content: "林川在雨中。",
      expected_baseline: "林川在废墟中。",
      baseline_content: "林川在细废墟中。",
      current_content: "林川在细雨中。",
    }));
    expect(onContentDiffChange).toHaveBeenCalledWith(expect.objectContaining({
      original_content: "林川在细废墟中。",
      current_content: "林川在细雨中。",
    }));
  });

  it("merges nearby changed fragments within a submitted replacement", () => {
    render(
      <NodeDetailDrawer
        node={{ id: "partial-inline", type: "chapter", label: "第一章", content: "甲新乙改丙丁戊己", extra_data: {} }}
        contentDiff={{
          original_content: "甲旧乙旧丙丁戊己",
          current_content: "甲新乙改丙丁戊己",
          hunks: [{ type: "replace", paragraph_index: 1, old_text: "甲旧乙旧丙丁戊己", new_text: "甲新乙改丙丁戊己" }],
        }}
        onClose={vi.fn()}
        onContentDiffDecision={vi.fn()}
        onContentDiffChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("inline-diff-new").textContent).toBe("甲新乙改丙丁戊己");
    expect(screen.getByTestId("inline-diff-new").querySelectorAll("[data-diff-kind]")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "查看修改原文" })).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "查看替换前文本" })).toBeNull();
    expect(screen.queryByRole("button", { name: "删除新增文本" })).toBeNull();
  });

  it.each([false, true])("deletes a green insertion while preserving the other pending replacement (grouped=%s)", async (grouped) => {
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    const onContentDiffChange = vi.fn();
    render(
      <NodeDetailDrawer
        node={{ id: "remove-inline-insert", type: "chapter", label: "第一章", content: "甲新增乙新丙丁戊己", extra_data: {} }}
        contentDiff={{
          ...(grouped ? { grouping: "agent_replacements" } : {}),
          original_content: "甲乙旧丙丁戊己",
          current_content: "甲新增乙新丙丁戊己",
          hunks: [{ type: "replace", paragraph_index: 1, ...(grouped ? { start_offset: 0 } : {}), old_text: "甲乙旧丙丁戊己", new_text: "甲新增乙新丙丁戊己" }],
        }}
        onClose={vi.fn()}
        onContentDiffDecision={onContentDiffDecision}
        onContentDiffChange={onContentDiffChange}
      />,
    );

    expect(screen.getByTestId("inline-diff-new").textContent).toBe("甲新增乙新丙丁戊己");
    fireEvent.click(screen.getByText("新增"));
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(screen.queryByRole("textbox", { name: "编辑新文内容" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "删除新增文本" }));
    await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledWith("remove-inline-insert", expect.objectContaining({
      expected_content: "甲新增乙新丙丁戊己", expected_baseline: "甲乙旧丙丁戊己",
      baseline_content: "甲乙旧丙丁戊己", current_content: "甲乙新丙丁戊己",
    })));
    await waitFor(() => expect(screen.getByTestId("inline-diff-new").textContent).toBe("甲乙新丙丁戊己"));
    expect(screen.queryByRole("button", { name: "删除新增文本" })).toBeNull();
    expect(screen.getByRole("button", { name: "查看修改原文" }).textContent).toBe("新");
  });

  it("keeps deleted diff text read-only", () => {
    render(
      <NodeDetailDrawer
        node={{ id: "plot-delete", type: "plot", label: "相遇", content: "", extra_data: {} }}
        contentDiff={{
          original_content: "“啪！”",
          current_content: "",
          hunks: [{ type: "delete", paragraph_index: 1, old_text: "“啪！”", new_text: "" }],
        }}
        onClose={vi.fn()}
        onContentDiffDecision={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "编辑新文" })).toBeNull();
    expect(screen.queryByRole("textbox", { name: "编辑新文内容" })).toBeNull();
  });

  it("shows chapter notes diffs inline and can revert a hunk", async () => {
    const onNotesDiffDecision = vi.fn().mockResolvedValue(undefined);
    const onNotesDiffChange = vi.fn();
    render(
      <NodeDetailDrawer
        node={{
          id: "chapter-notes",
          type: "chapter",
          label: "第一章",
          content: "正文。",
          notes: "事实：新晶核。",
          extra_data: {},
        }}
        notesDiff={{
          original_content: "事实：旧晶核。",
          current_content: "事实：新晶核。",
          hunks: [{
            type: "replace",
            paragraph_index: 1,
            old_text: "事实：旧晶核。",
            new_text: "事实：新晶核。",
          }],
        }}
        onClose={vi.fn()}
        onNotesDiffDecision={onNotesDiffDecision}
        onNotesDiffChange={onNotesDiffChange}
      />,
    );

    const notes = screen.getByText("章节笔记").closest("details");
    expect(notes.open).toBe(false);
    fireEvent.click(screen.getByText("章节笔记"));
    expect(notes.open).toBe(true);
    expect(screen.getByTestId("chapter-notes").textContent).toContain("事实：新晶核。");
    fireEvent.click(screen.getByRole("button", { name: "对照" }));
    expect(screen.getByTestId("inline-diff-old").textContent).toBe("事实：旧晶核。");
    fireEvent.click(screen.getAllByRole("button", { name: "撤回修改" })[0]);
    await waitFor(() => expect(onNotesDiffDecision).toHaveBeenCalledWith("chapter-notes", expect.objectContaining({
      expected_notes: "事实：新晶核。",
      current_notes: "事实：旧晶核。",
      baseline_notes: "事实：旧晶核。",
    })));
    expect(onNotesDiffChange).toHaveBeenCalledWith(null);
  });

  it("shows streaming preview diffs without apply or revert actions", () => {
    const node = {
      id: "chapter-preview",
      type: "chapter",
      label: "第一章",
      content: "旧文",
      extra_data: {},
    };
    render(
      <NodeDetailDrawer
        node={node}
        contentDiff={{
          preview: true,
          original_content: "旧文",
          current_content: "新文",
          hunks: [{
            type: "replace",
            paragraph_index: 1,
            old_text: "旧文",
            new_text: "新文",
          }],
        }}
        onClose={vi.fn()}
        onUpdate={vi.fn()}
      />,
    );

    expect(screen.getByText("生成预览")).toBeDefined();
    expect(screen.getAllByTestId("inline-diff-hunk")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "保留修改" })).toBeNull();
    expect(screen.queryByRole("button", { name: "撤回修改" })).toBeNull();
    expect(screen.queryByRole("button", { name: "全部保留" })).toBeNull();
    expect(screen.queryByRole("button", { name: "全部撤回" })).toBeNull();
  });

  it("keeps preview diffs read-only while the agent is still running", () => {
    render(
      <NodeDetailDrawer
        node={{
          id: "chapter-preview",
          type: "chapter",
          label: "第一章",
          content: "旧文",
          extra_data: {},
        }}
        contentDiff={{
          preview: true,
          original_content: "旧文",
          current_content: "新文",
          hunks: [{
            type: "replace",
            paragraph_index: 1,
            old_text: "旧文",
            new_text: "新文",
          }],
        }}
        agentRunning
        onClose={vi.fn()}
        onUpdate={vi.fn()}
      />,
    );

    expect(screen.getByText("生成预览")).toBeDefined();
    expect(screen.queryByRole("button", { name: "保留修改" })).toBeNull();
    expect(screen.queryByRole("button", { name: "撤回修改" })).toBeNull();
  });

  it("does not write again when accepting a full-chapter insert that is already saved", async () => {
    const chapter = "第一段。\n\n第二段。\n\n第三段。";
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    const onContentDiffChange = vi.fn();
    render(
      <NodeDetailDrawer
        node={{
          id: "chapter-3",
          type: "chapter",
          label: "第三章",
          content: chapter,
          extra_data: {},
        }}
        contentDiff={{
          original_content: "",
          current_content: chapter,
          hunks: [{
            type: "insert_after",
            paragraph_index: 0,
            old_text: "",
            new_text: chapter,
          }],
        }}
        agentRunning={false}
        onClose={vi.fn()}
        onUpdate={onUpdate}
        onContentDiffDecision={onContentDiffDecision}
        onContentDiffChange={onContentDiffChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "全部保留" }));
    await waitFor(() => {
      expect(onContentDiffChange).toHaveBeenCalledWith(null);
    });
    expect(onUpdate).not.toHaveBeenCalled();
    expect(onContentDiffDecision).toHaveBeenCalledWith("chapter-3", expect.objectContaining({
      baseline_content: chapter, current_content: chapter,
    }));
  });

  it("reverts a single pending hunk back to the original paragraph", async () => {
    const node = {
      id: "plot-2",
      type: "plot",
      label: "废墟相遇",
      content: "开场。\n\n林川在雨中遇见苏婉。",
      extra_data: {},
    };
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    const onContentDiffChange = vi.fn();
    render(
      <NodeDetailDrawer
        node={node}
        contentDiff={{
          hunks: [{
            type: "replace",
            paragraph_index: 2,
            old_text: "林川在废墟中遇见苏婉。",
            new_text: "林川在雨中遇见苏婉。",
          }],
        }}
        onClose={vi.fn()}
        onUpdate={onUpdate}
        onContentDiffDecision={onContentDiffDecision}
        onContentDiffChange={onContentDiffChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "撤回修改" }));
    await waitFor(() => {
      expect(onContentDiffDecision).toHaveBeenCalledWith("plot-2", expect.objectContaining({
        current_content: "开场。\n\n林川在废墟中遇见苏婉。",
      }));
    });
    expect(onContentDiffChange).toHaveBeenCalledWith(null);
  });

  it("moves only the accepted paragraph into the cross-device baseline", async () => {
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    const onContentDiffChange = vi.fn();
    render(<NodeDetailDrawer
      node={{ id: "chapter-partial", type: "chapter", label: "第一章",
        content: "第一段新。\n\n第二段新。", extra_data: {} }}
      contentDiff={{ original_content: "第一段旧。\n\n第二段旧。",
        current_content: "第一段新。\n\n第二段新。",
        hunks: [
          { type: "replace", paragraph_index: 1, old_text: "第一段旧。", new_text: "第一段新。" },
          { type: "replace", paragraph_index: 2, old_text: "第二段旧。", new_text: "第二段新。" },
        ] }}
      onContentDiffDecision={onContentDiffDecision}
      onContentDiffChange={onContentDiffChange}
      onClose={vi.fn()}
    />);

    fireEvent.click(screen.getAllByRole("button", { name: "保留修改" })[0]);
    await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledWith("chapter-partial", {
      expected_content: "第一段新。\n\n第二段新。",
      expected_baseline: "第一段旧。\n\n第二段旧。",
      baseline_content: "第一段新。\n\n第二段旧。",
      current_content: "第一段新。\n\n第二段新。",
    }));
    expect(onContentDiffChange).toHaveBeenCalledWith(expect.objectContaining({
      hunks: [{ type: "replace", paragraph_index: 2, old_text: "第二段旧。", new_text: "第二段新。" }],
    }));
  });

  it("uses the refreshed node content for concurrency checks after a streaming preview", async () => {
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer
      node={{ id: "chapter-refreshed", type: "chapter", label: "第一章",
        content: "Agent 最终提交正文", extra_data: {} }}
      contentDiff={{
        original_content: "修改前正文",
        current_content: "流式预览中的旧快照",
        hunks: [{
          type: "replace",
          paragraph_index: 1,
          old_text: "修改前正文",
          new_text: "Agent 最终提交正文",
        }],
      }}
      onContentDiffDecision={onContentDiffDecision}
      onContentDiffChange={vi.fn()}
      onClose={vi.fn()}
    />);

    fireEvent.click(screen.getByRole("button", { name: "全部保留" }));

    await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledWith(
      "chapter-refreshed",
      expect.objectContaining({ expected_content: "Agent 最终提交正文" }),
    ));
  });

  it("uses the finalized diff content when the canvas node refresh is still pending", async () => {
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer
      node={{ id: "chapter-stale", type: "chapter", label: "第一章",
        content: "Agent 修改前正文", extra_data: {} }}
      contentDiff={{
        original_content: "Agent 修改前正文",
        current_content: "Agent 最终提交正文",
        hunks: [{
          type: "replace",
          paragraph_index: 1,
          old_text: "Agent 修改前正文",
          new_text: "Agent 最终提交正文",
        }],
      }}
      onContentDiffDecision={onContentDiffDecision}
      onContentDiffChange={vi.fn()}
      onClose={vi.fn()}
    />);

    fireEvent.click(screen.getByRole("button", { name: "保留修改" }));

    await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledWith(
      "chapter-stale",
      expect.objectContaining({
        expected_content: "Agent 最终提交正文",
        expected_baseline: "Agent 修改前正文",
      }),
    ));
  });

  it("hydrates inline diffs from node content when the stored diff has no original_content", () => {
    const node = {
      id: "plot-4",
      type: "plot",
      label: "废墟相遇",
      content: "开场改。\n\n林川在废墟中遇见苏婉。",
      extra_data: {},
    };
    render(
      <NodeDetailDrawer
        node={node}
        contentDiff={{
          hunks: [{
            type: "replace",
            paragraph_index: 1,
            old_text: "开场。",
            new_text: "开场改。",
          }],
        }}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByTestId("inline-diff-hunk")).toBeDefined();
    expect(screen.getByTestId("inline-diff-new").textContent).toBe("开场改。");
  });

  it("gives every paragraph its own toolbar and rejects only that paragraph", async () => {
    const old = "A\n\nB\n\nC";
    const next = "X\n\nA′\n\nB′\n\nC′";
    const onDecision = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer
      node={{ id: "grouped", type: "chapter", label: "章节", content: next, extra_data: {} }}
      contentDiff={{ grouping: "agent_replacements", original_content: old, current_content: next,
        hunks: [{ type: "replace", start_offset: 0, old_text: old, new_text: next }] }}
      onContentDiffDecision={onDecision} onContentDiffChange={vi.fn()} onClose={vi.fn()}
    />);
    expect(screen.getAllByRole("button", { name: "保留修改" })).toHaveLength(4);
    expect(screen.getAllByRole("button", { name: "撤回修改" })).toHaveLength(4);
    fireEvent.click(screen.getAllByRole("button", { name: "撤回修改" })[1]);
    await waitFor(() => expect(onDecision).toHaveBeenCalledWith("grouped", expect.objectContaining({
      expected_content: next, expected_baseline: old,
      baseline_content: old, current_content: "X\n\nA\n\nB′\n\nC′",
      groups: expect.any(Array),
    })));
    expect(screen.getAllByRole("button", { name: "撤回修改" })).toHaveLength(3);
  });

  it("keeps every agent group with one decision when accepting all", async () => {
    const old = "甲旧。\n\n乙旧。";
    const next = "甲新。\n\n乙新。";
    const onDecision = vi.fn().mockResolvedValue(undefined);
    decideAgentGroup.mockClear();
    render(<NodeDetailDrawer
      node={{ id: "chapter-keep-all", type: "chapter", label: "第一章", content: next, extra_data: {} }}
      contentDiff={{
        grouping: "agent_replacements",
        original_content: old,
        current_content: next,
        hunks: [
          { type: "replace", start_offset: 0, old_text: "甲旧。", new_text: "甲新。" },
          { type: "replace", start_offset: Array.from("甲旧。\n\n").length, old_text: "乙旧。", new_text: "乙新。" },
        ],
      }}
      onContentDiffDecision={onDecision}
      onContentDiffChange={vi.fn()}
      onClose={vi.fn()}
    />);

    fireEvent.click(screen.getByRole("button", { name: "全部保留" }));

    await waitFor(() => expect(onDecision).toHaveBeenCalledWith("chapter-keep-all", expect.objectContaining({
      baseline_content: next,
      current_content: next,
      groups: [],
    })));
    expect(onDecision).toHaveBeenCalledTimes(1);
  });

  it("can edit an unchanged paragraph while an agent group is pending", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer
      node={{ id: "group-edit", type: "plot", label: "分组", content: "甲新。\n\n乙原文。", extra_data: {} }}
      contentDiff={{ grouping: "agent_replacements", original_content: "甲旧。\n\n乙原文。",
        current_content: "甲新。\n\n乙原文。",
        hunks: [{ type: "replace", start_offset: 0, old_text: "甲旧。", new_text: "甲新。" }] }}
      onUpdate={onUpdate} onClose={vi.fn()}
    />);
    fireEvent.click(screen.getByText("乙原文。"));
    fireEvent.change(screen.getByRole("textbox", { name: "编辑段落内容" }), { target: { value: "乙手改。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存段落" }));
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith("group-edit", {
      content: "甲新。\n\n乙手改。", expected_content: "甲新。\n\n乙原文。",
    }));
  });

  it("shows only the net diff from the original baseline to current content", () => {
    const node = {
      id: "plot-3",
      type: "plot",
      label: "废墟相遇",
      content: "开场改。\n\n林川在雨中遇见苏婉。",
      extra_data: {},
    };
    render(
      <NodeDetailDrawer
        node={node}
        contentDiff={{
          original_content: "开场。\n\n林川在废墟中遇见苏婉。",
          current_content: "开场改。\n\n林川在雨中遇见苏婉。",
          hunks: [
            { type: "replace", paragraph_index: 1, old_text: "开场。", new_text: "开场改。" },
            { type: "replace", paragraph_index: 2, old_text: "林川在废墟中遇见苏婉。", new_text: "林川在雨中遇见苏婉。" },
          ],
        }}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getAllByTestId("inline-diff-hunk")).toHaveLength(2);
    expect(screen.getAllByTestId("inline-diff-new").map((row) => row.textContent)).toEqual([
      "开场改。",
      "林川在雨中遇见苏婉。",
    ]);
  });

  it("renders character storylines as named tracks with step list", () => {
    const node = {
      id: "char-1",
      type: "character",
      label: "林川",
      content: "人设正文",
      extra_data: {
        storylines: [
          {
            name: "力量线",
            description: "明线，升级节奏。",
            body: ["血雨觉醒", "归墟补天"],
          },
        ],
      },
    };

    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(screen.getByText("发展线")).toBeDefined();
    expect(screen.getByText("力量线")).toBeDefined();
    expect(screen.getByText("明线，升级节奏。")).toBeDefined();
    expect(screen.getByText("血雨觉醒")).toBeDefined();
    expect(screen.getByText("归墟补天")).toBeDefined();
    expect(screen.queryByText(/storylines/)).toBeNull();
  });

  it("edits character storylines in edit mode and includes them in onUpdate payload", async () => {
    const node = {
      id: "char-2",
      type: "character",
      label: "林川",
      content: "人设",
      extra_data: {
        storylines: [
          { name: "力量线", description: "明线", body: ["觉醒", "补天"] },
        ],
      },
    };
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByTitle("编辑全文"));
    fireEvent.change(screen.getByDisplayValue("力量线"), { target: { value: "力量线（改）" } });
    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith("char-2", expect.objectContaining({
        storylines: [
          expect.objectContaining({ name: "力量线（改）", description: "明线", body: ["觉醒", "补天"] }),
        ],
      }));
    });
  });

  it("renders missing planning items when sync check fails", () => {
    const node = {
      id: "node-1",
      type: "chapter",
      label: "第一章",
      content: "正文",
      extra_data: {
        last_generation: {
          sync_evaluations: [
            {
              passed: false,
              plan_alignment: {
                completed: [],
                missing: ["章末发现移交单"],
              },
            },
          ],
        },
      },
    };

    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(screen.getByText("同步检查未通过")).toBeDefined();
    expect(screen.getByText("章末发现移交单")).toBeDefined();
  });

  it("renders nothing when node is null", () => {
    const { container } = render(<NodeDetailDrawer node={null} onClose={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it("toggles between sidebar and fullscreen modes", () => {
    const node = { id: "fullscreen-node", type: "outline", label: "大纲", content: "正文" };
    const { container } = render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    const fullscreenButton = screen.getByTitle("全屏查看");
    expect(container.querySelector(".w-\\[420px\\]")).not.toBeNull();

    fireEvent.click(fullscreenButton);

    expect(screen.getByTitle("退出全屏")).toBeDefined();
    expect(container.querySelector(".w-full.h-full")).not.toBeNull();
  });

  it("keeps fullscreen mode when navigating between chapters on web", () => {
    const chapters = [
      { id: "chapter-1", type: "chapter", label: "第一章", content: "第一章正文" },
      { id: "chapter-2", type: "chapter", label: "第二章", content: "第二章正文" },
    ];
    const onChapterNavigate = vi.fn();
    const props = {
      onClose: vi.fn(),
      chapterNodes: chapters,
      onChapterNavigate,
    };
    const { container, rerender } = render(
      <NodeDetailDrawer {...props} node={chapters[0]} />,
    );

    fireEvent.click(screen.getByTitle("全屏查看"));
    fireEvent.click(screen.getByTitle("下一章"));
    expect(onChapterNavigate).toHaveBeenCalledWith(chapters[1]);

    rerender(<NodeDetailDrawer {...props} node={chapters[1]} />);

    expect(screen.getByTitle("退出全屏")).toBeDefined();
    expect(container.querySelector(".w-full.h-full")).not.toBeNull();
  });

  it("switches chapters with horizontal swipes and does not render navigation buttons", () => {
    const chapters = [
      { id: "chapter-1", type: "chapter", label: "第一章", content: "第一章正文" },
      { id: "chapter-2", type: "chapter", label: "第二章", content: "第二章正文" },
      { id: "chapter-3", type: "chapter", label: "第三章", content: "第三章正文" },
    ];
    const onChapterNavigate = vi.fn();
    render(
      <NodeDetailDrawer
        appMode
        node={chapters[1]}
        onClose={vi.fn()}
        chapterNodes={chapters}
        onChapterNavigate={onChapterNavigate}
      />,
    );

    const scroller = screen.getByTestId("node-detail-scroll");
    expect(scroller.className).toMatch(/pb-(24|28|32)/);
    expect(screen.queryByTitle("上一章")).toBeNull();
    expect(screen.queryByTitle("下一章")).toBeNull();

    fireEvent.touchStart(scroller, { touches: [{ clientX: 240, clientY: 120 }] });
    fireEvent.touchEnd(scroller, { changedTouches: [{ clientX: 120, clientY: 126 }] });
    expect(onChapterNavigate).toHaveBeenCalledWith(chapters[2]);

    onChapterNavigate.mockClear();
    fireEvent.touchStart(scroller, { touches: [{ clientX: 120, clientY: 120 }] });
    fireEvent.touchEnd(scroller, { changedTouches: [{ clientX: 240, clientY: 124 }] });
    expect(onChapterNavigate).toHaveBeenCalledWith(chapters[0]);
  });

  it("adds extra bottom padding in app mode so the last lines clear the composer", () => {
    render(
      <NodeDetailDrawer
        appMode
        node={{ id: "plot-1", type: "plot", label: "主线", content: "最后两行不该被挡住" }}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByTestId("node-detail-scroll").className).toMatch(/pb-(24|28|32)/);
  });

  it("uses a book-like pale yellow background for chapter details", () => {
    const { container } = render(
      <NodeDetailDrawer
        node={{ id: "chapter-paper", type: "chapter", label: "第一章", content: "正文" }}
        onClose={vi.fn()}
      />,
    );

    expect(container.querySelector(".bg-amber-50")).not.toBeNull();
  });

  it("navigates chapters by sort_order with side buttons on web", () => {
    const chapters = [
      { id: "chapter-3", type: "chapter", label: "第三章", content: "第三章正文", sort_order: 3 },
      { id: "chapter-2", type: "chapter", label: "第二章", content: "第二章正文", sort_order: 2 },
      { id: "chapter-1", type: "chapter", label: "第一章", content: "第一章正文", sort_order: 1 },
    ];
    const onChapterNavigate = vi.fn();
    render(
      <NodeDetailDrawer
        node={chapters[1]}
        onClose={vi.fn()}
        chapterNodes={chapters}
        onChapterNavigate={onChapterNavigate}
      />,
    );

    fireEvent.click(screen.getByTitle("上一章"));
    expect(onChapterNavigate).toHaveBeenCalledWith(chapters[2]);
    onChapterNavigate.mockClear();
    fireEvent.click(screen.getByTitle("下一章"));
    expect(onChapterNavigate).toHaveBeenCalledWith(chapters[0]);
  });

  it("does not navigate chapters with swipes on web", () => {
    const chapters = [
      { id: "chapter-1", type: "chapter", label: "第一章", content: "第一章正文" },
      { id: "chapter-2", type: "chapter", label: "第二章", content: "第二章正文" },
    ];
    const onChapterNavigate = vi.fn();
    render(
      <NodeDetailDrawer
        node={chapters[0]}
        onClose={vi.fn()}
        chapterNodes={chapters}
        onChapterNavigate={onChapterNavigate}
      />,
    );

    const scroller = screen.getByTestId("node-detail-scroll");
    fireEvent.touchStart(scroller, { touches: [{ clientX: 240, clientY: 120 }] });
    fireEvent.touchEnd(scroller, { changedTouches: [{ clientX: 120, clientY: 126 }] });
    expect(onChapterNavigate).not.toHaveBeenCalled();
  });

  it("disables the previous chapter button on the first chapter and the next button on the last", () => {
    const chapters = [
      { id: "chapter-1", type: "chapter", label: "第一章", content: "第一章正文" },
      { id: "chapter-2", type: "chapter", label: "第二章", content: "第二章正文" },
    ];
    const onChapterNavigate = vi.fn();
    const { rerender } = render(
      <NodeDetailDrawer
        node={chapters[0]}
        onClose={vi.fn()}
        chapterNodes={chapters}
        onChapterNavigate={onChapterNavigate}
      />,
    );

    expect(screen.getByTitle("上一章").disabled).toBe(true);
    fireEvent.click(screen.getByTitle("下一章"));
    expect(onChapterNavigate).toHaveBeenCalledWith(chapters[1]);

    rerender(
      <NodeDetailDrawer
        node={chapters[1]}
        onClose={vi.fn()}
        chapterNodes={chapters}
        onChapterNavigate={onChapterNavigate}
      />,
    );
    expect(screen.getByTitle("下一章").disabled).toBe(true);
  });

  it("uses a wider chapter body", () => {
    render(
      <NodeDetailDrawer
        appMode
        node={{ id: "chapter-wide", type: "chapter", label: "第一章", content: "正文" }}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByTestId("chapter-body").className).toContain("max-w-5xl");
  });

  it("enlarges chapter typography in fullscreen mode", () => {
    const node = { id: "large-chapter", type: "chapter", label: "第一章", content: "正文" };
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(screen.getByTestId("chapter-prose").className).toContain("text-lg");
    expect(screen.getByTestId("chapter-prose").className).toContain("leading-[2.4]");
    fireEvent.click(screen.getByTitle("全屏查看"));

    expect(screen.getByTestId("chapter-prose").className).toContain("text-xl");
    expect(screen.getByTestId("chapter-prose").className).toContain("leading-[2.4]");
    expect(screen.getByRole("heading", { name: "第一章" }).className).toContain("text-2xl");
  });

  it("uses a wider gap between chapter paragraphs than within a paragraph", () => {
    render(
      <NodeDetailDrawer
        node={{
          id: "chapter-spacing",
          type: "chapter",
          label: "第一章",
          content: "第一段第一行\n还在段内。\n\n第二段。",
          extra_data: {},
        }}
        onClose={vi.fn()}
        onUpdate={vi.fn()}
      />,
    );

    const stack = screen.getByTestId("chapter-paragraphs");
    expect(stack.className).toContain("gap-8");
    const paragraphs = stack.querySelectorAll("p");
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0].className).toContain("leading-[2.4]");
    expect(paragraphs[0].textContent).toBe("第一段第一行\n还在段内。");
    expect(paragraphs[1].textContent).toBe("第二段。");
  });

  it("restores the last scroll position when reopening the same node", async () => {
    const node = {
      id: "remember-scroll-node",
      type: "chapter",
      label: "第一章",
      content: "正文",
      extra_data: {},
    };
    const { rerender } = render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);
    const scrollContainer = screen.getByTestId("node-detail-scroll");

    fireEvent.scroll(scrollContainer, { target: { scrollTop: 240 } });
    expect(scrollContainer.scrollTop).toBe(240);

    rerender(<NodeDetailDrawer node={null} onClose={vi.fn()} />);
    rerender(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("node-detail-scroll").scrollTop).toBe(240);
    });
  });

  it("does not show pin or delete actions in the node detail header", () => {
    render(
      <NodeDetailDrawer
        node={{ id: "n1", type: "idea", label: "测试节点", content: "" }}
        onClose={vi.fn()}
        onDelete={vi.fn()}
        onToggleLocked={vi.fn()}
      />,
    );

    expect(screen.queryByTitle("删除节点")).toBeNull();
    expect(screen.queryByTitle("固定节点（固定后坐标锁定，agent 与拖拽都无法移动）")).toBeNull();
    expect(screen.queryByTitle("取消固定（固定后坐标锁定，agent 与拖拽都无法移动）")).toBeNull();
  });

  it("enters edit mode and calls onUpdate with new title/content on save", async () => {
    const node = { id: "n1", type: "outline", label: "原标题", content: "原内容" };
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByTitle("编辑全文"));

    const titleInput = screen.getByDisplayValue("原标题");
    const contentArea = screen.getByDisplayValue("原内容");
    fireEvent.change(titleInput, { target: { value: "新标题" } });
    fireEvent.change(contentArea, { target: { value: "新内容" } });

    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith("n1", {
        title: "新标题",
        content: "新内容",
        expected_content: "原内容",
      });
    });
  });

  it("opens the content editor at the current reading position", () => {
    const content = Array.from({ length: 100 }, (_, index) => `第${index + 1}段正文`).join("\n");
    render(
      <NodeDetailDrawer
        node={{ id: "chapter-scroll", type: "chapter", label: "长章节", content, extra_data: {} }}
        onClose={vi.fn()}
        onUpdate={vi.fn()}
      />,
    );

    const reader = screen.getByTestId("node-detail-scroll");
    Object.defineProperty(reader, "scrollHeight", { configurable: true, value: 2000 });
    Object.defineProperty(reader, "clientHeight", { configurable: true, value: 500 });
    reader.scrollTop = 750;

    const scrollHeight = vi.spyOn(HTMLTextAreaElement.prototype, "scrollHeight", "get").mockReturnValue(1200);
    const clientHeight = vi.spyOn(HTMLTextAreaElement.prototype, "clientHeight", "get").mockReturnValue(400);
    fireEvent.click(screen.getByTitle("编辑全文"));

    const editor = screen.getByDisplayValue(content, { normalizer: (value) => value });
    scrollHeight.mockRestore();
    clientHeight.mockRestore();
    expect(editor.scrollTop).toBe(400);
  });

  it("returns to the previous reading position after saving an edit", async () => {
    const scheduledFrames = [];
    const requestFrame = vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      scheduledFrames.push(callback);
      return scheduledFrames.length;
    });
    const cancelFrame = vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => {});
    const content = Array.from({ length: 100 }, (_, index) => `第${index + 1}段正文`).join("\n");
    const onUpdate = vi.fn().mockResolvedValue(undefined);

    render(
      <NodeDetailDrawer
        node={{ id: "chapter-return-scroll", type: "chapter", label: "长章节", content, extra_data: {} }}
        onClose={vi.fn()}
        onUpdate={onUpdate}
      />,
    );

    scheduledFrames.shift()?.();
    const reader = screen.getByTestId("node-detail-scroll");
    Object.defineProperty(reader, "scrollHeight", { configurable: true, value: 2000 });
    Object.defineProperty(reader, "clientHeight", { configurable: true, value: 500 });
    reader.scrollTop = 750;

    fireEvent.click(screen.getByTitle("编辑全文"));
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() => expect(onUpdate).toHaveBeenCalled());

    const restoredReader = await screen.findByTestId("node-detail-scroll");
    Object.defineProperty(restoredReader, "scrollHeight", { configurable: true, value: 3000 });
    Object.defineProperty(restoredReader, "clientHeight", { configurable: true, value: 500 });
    scheduledFrames.splice(0).forEach((callback) => callback());

    expect(restoredReader.scrollTop).toBe(1250);
    requestFrame.mockRestore();
    cancelFrame.mockRestore();
  });

  it("edits existing chapter_elements in edit mode and includes them in onUpdate payload", async () => {
    const node = {
      id: "c1",
      type: "chapter",
      label: "第一章",
      content: "正文",
      extra_data: {
        chapter_elements: [
          { id: "e1", title: "主角觉醒", content: "林远感知异常" },
        ],
      },
    };
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByTitle("编辑全文"));

    const titleInput = screen.getByDisplayValue("主角觉醒");
    fireEvent.change(titleInput, { target: { value: "主角觉醒（改）" } });

    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith("c1", expect.objectContaining({
        chapter_elements: [
          expect.objectContaining({ id: "e1", title: "主角觉醒（改）", content: "林远感知异常" }),
        ],
      }));
    });
  });

  it("adds a new chapter element in edit mode", async () => {
    const node = {
      id: "c2",
      type: "chapter",
      label: "第二章",
      content: "",
      extra_data: { chapter_elements: [] },
    };
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByTitle("编辑全文"));

    fireEvent.click(screen.getByText("添加元素"));
    const titleInputs = screen.getAllByPlaceholderText("元素标题");
    fireEvent.change(titleInputs[0], { target: { value: "新元素" } });

    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith("c2", expect.objectContaining({
        chapter_elements: [
          expect.objectContaining({ title: "新元素" }),
        ],
      }));
    });
  });

  it("removes a chapter element in edit mode", async () => {
    const node = {
      id: "c3",
      type: "chapter",
      label: "第三章",
      content: "",
      extra_data: {
        chapter_elements: [
          { id: "e1", title: "保留", content: "" },
          { id: "e2", title: "删除我", content: "" },
        ],
      },
    };
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByTitle("编辑全文"));

    const removeButtons = screen.getAllByTitle("删除元素");
    fireEvent.click(removeButtons[1]);

    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => {
      const payload = onUpdate.mock.calls[0][1];
      expect(payload.chapter_elements).toHaveLength(1);
      expect(payload.chapter_elements[0]).toEqual(expect.objectContaining({ id: "e1", title: "保留" }));
    });
  });

  it("does not render chapter elements editor for non-chapter nodes in edit mode", () => {
    const node = { id: "p1", type: "plot", label: "情节", content: "" };
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onUpdate={vi.fn()} />);

    fireEvent.click(screen.getByTitle("编辑全文"));

    expect(screen.queryByText("添加元素")).toBeNull();
    expect(screen.queryByPlaceholderText("元素标题")).toBeNull();
  });
});


describe("local original-text decisions", () => {
  it.each([false, true])("persists restore/delete independently and retains the other pending change (grouped=%s)", async (grouped) => {
    const original = "始祖血脉在体内涌动，旧光照亮石室。";
    const current = "霸道血气在体内涌动，新光照亮石室。";
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    const onContentDiffChange = vi.fn();
    render(<NodeDetailDrawer
      node={{ id: "local-decisions", type: "chapter", label: "第一章", content: current, extra_data: {} }}
      contentDiff={{ ...(grouped ? { grouping: "agent_replacements" } : {}), original_content: original, current_content: current,
        hunks: [{ type: "replace", paragraph_index: 1, ...(grouped ? { start_offset: 0 } : {}), old_text: original, new_text: current }] }}
      onClose={vi.fn()} onContentDiffDecision={onContentDiffDecision} onContentDiffChange={onContentDiffChange}
    />);
    fireEvent.click(screen.getByText("霸道血气"));
    fireEvent.click(screen.getByRole("button", { name: "恢复" }));
    await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledWith("local-decisions", expect.objectContaining({
      expected_content: current, expected_baseline: original, baseline_content: original,
      current_content: "始祖血脉在体内涌动，新光照亮石室。",
    })));
    await waitFor(() => expect(screen.queryByText("霸道血气")).toBeNull());
    fireEvent.click(screen.getByText("新"));
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    await waitFor(() => expect(onContentDiffDecision).toHaveBeenLastCalledWith("local-decisions", expect.objectContaining({
      expected_content: "始祖血脉在体内涌动，新光照亮石室。", expected_baseline: original,
      baseline_content: "始祖血脉在体内涌动，新光照亮石室。",
      current_content: "始祖血脉在体内涌动，新光照亮石室。",
    })));
    await waitFor(() => expect(onContentDiffChange).toHaveBeenLastCalledWith(null));
  });
});


it.each([false, true])("removes an inserted chapter paragraph and saves the remaining text (grouped=%s)", async (grouped) => {
  const original = "首段。";
  const current = "首段。\n\n新增段。";
  const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
  const onContentDiffChange = vi.fn();
  const { rerender } = render(<NodeDetailDrawer
    node={{ id: "delete-inserted-paragraph", type: "chapter", label: "章节", content: current, extra_data: {} }}
    contentDiff={{ ...(grouped ? { grouping: "agent_replacements" } : {}), original_content: original, current_content: current,
      hunks: [{ type: "insert_after", paragraph_index: 1, ...(grouped ? { start_offset: original.length } : {}), old_text: "", new_text: grouped ? "\n\n新增段。" : "新增段。" }] }}
    onClose={vi.fn()} onContentDiffDecision={onContentDiffDecision} onContentDiffChange={onContentDiffChange}
  />);
  fireEvent.click(screen.getByRole("button", { name: "删除新增文本" }));
  await waitFor(() => expect(onContentDiffDecision).toHaveBeenCalledWith("delete-inserted-paragraph", expect.objectContaining({
    expected_content: current, expected_baseline: original, baseline_content: original, current_content: original,
  })));
  await waitFor(() => expect(onContentDiffChange).toHaveBeenLastCalledWith(null));
  expect(screen.queryByText("新增段。")).toBeNull();
  rerender(<NodeDetailDrawer
    node={{ id: "delete-inserted-paragraph", type: "chapter", label: "章节", content: "用户手动更新的正文。", extra_data: {} }}
    contentDiff={null} onClose={vi.fn()} onContentDiffDecision={onContentDiffDecision} onContentDiffChange={onContentDiffChange}
  />);
  expect(screen.getByText("用户手动更新的正文。")).toBeTruthy();
});

it.each([
  ["", "新增甲。\n\n新增乙。", 0, "撤回修改", "", "新增乙。"],
  ["", "新增甲。\n\n新增乙。", 0, "保留修改", "新增甲。", "新增甲。\n\n新增乙。"],
  ["删除甲。\n\n删除乙。", "", 0, "保留修改", "删除乙。", ""],
  ["删除甲。\n\n删除乙。", "", 1, "撤回修改", "删除甲。\n\n删除乙。", "删除乙。"],
  ["😀甲的旧正文。\n\n乙的旧正文。", "😀甲的新正文。\n\n乙的新正文。", 1, "撤回修改", "😀甲的旧正文。\n\n乙的旧正文。", "😀甲的新正文。\n\n乙的旧正文。"],
])("persists one paragraph decision independently: %s -> %s (%s %s)", async (old, current, index, action, baseline, next) => {
  const { applyAgentGroups } = await import("../../lib/agentContentDiff");
  const onDecision = vi.fn().mockResolvedValue(undefined);
  const onChange = vi.fn();
  const props = { onClose: vi.fn(), onContentDiffDecision: onDecision, onContentDiffChange: onChange };
  const { rerender } = render(<NodeDetailDrawer {...props}
    node={{ id: "paragraph-decision", type: "chapter", label: "章节", content: current, extra_data: {} }}
    contentDiff={{ grouping: "agent_replacements", original_content: old, current_content: current,
      hunks: [{ start_offset: 0, old_text: old, new_text: current }] }}
  />);
  expect(screen.getAllByRole("button", { name: action })).toHaveLength(2);
  fireEvent.click(screen.getAllByRole("button", { name: action })[index]);
  await waitFor(() => expect(onDecision).toHaveBeenCalledTimes(1));
  const payload = onDecision.mock.calls[0][1];
  expect(payload.baseline_content).toBe(baseline);
  expect(payload.current_content).toBe(next);
  expect(applyAgentGroups(baseline, payload.groups)).toBe(next);
  await waitFor(() => expect(screen.getAllByRole("button", { name: action })).toHaveLength(1));
  const savedDiff = onChange.mock.calls.at(-1)[0];
  rerender(<NodeDetailDrawer {...props}
    node={{ id: "paragraph-decision", type: "chapter", label: "章节", content: next, extra_data: {} }}
    contentDiff={savedDiff}
  />);
  expect(screen.getAllByRole("button", { name: action })).toHaveLength(1);
});

it("switches comparison for just one paragraph", () => {
  render(<NodeDetailDrawer node={{ id: "compare-paragraph", type: "chapter", label: "章节", content: "甲的新正文。\n\n乙的新正文。", extra_data: {} }}
    contentDiff={{ grouping: "agent_replacements", original_content: "甲的旧正文。\n\n乙的旧正文。", hunks: [
      { start_offset: 0, old_text: "甲的旧正文。\n\n乙的旧正文。", new_text: "甲的新正文。\n\n乙的新正文。" },
    ] }} onClose={vi.fn()} />);
  expect(screen.getAllByRole("button", { name: "对照" })).toHaveLength(2);
  fireEvent.click(screen.getAllByRole("button", { name: "对照" })[1]);
  expect(screen.getAllByRole("button", { name: "结果" })).toHaveLength(1);
  expect(screen.getAllByRole("button", { name: "对照" })).toHaveLength(1);
  expect(screen.getByTestId("inline-diff-old").textContent).toBe("乙的旧正文。");
});

it("also separates consecutive inserted paragraphs in legacy diffs", async () => {
  const onDecision = vi.fn().mockResolvedValue(undefined);
  render(<NodeDetailDrawer node={{ id: "legacy-insert", type: "chapter", label: "章节", content: "甲。\n\n乙。", extra_data: {} }}
    contentDiff={{ original_content: "", current_content: "甲。\n\n乙。", hunks: [
      { type: "insert_after", paragraph_index: 0, old_text: "", new_text: "甲。\n\n乙。" },
    ] }} onClose={vi.fn()} onContentDiffDecision={onDecision} onContentDiffChange={vi.fn()} />);
  expect(screen.getAllByRole("button", { name: "撤回修改" })).toHaveLength(2);
  fireEvent.click(screen.getAllByRole("button", { name: "撤回修改" })[1]);
  await waitFor(() => expect(onDecision).toHaveBeenCalledWith("legacy-insert", expect.objectContaining({
    baseline_content: "", current_content: "甲。",
  })));
});


it("reviews unrelated paragraphs independently after a whole-chapter submission and reload", async () => {
  const old = "梁超背着鼓鼓囊囊的战术包跑在最前头，两只脚倒腾得飞快。他一边跑一边揪住身旁一个学生的肩膀往后一推，自己借力窜出两步。被推倒的学生膝盖还没撑起来，一头四肢着地的丧尸已经扑上去，惨叫只响了半截。";
  const next = "他没回头，肩膀一沉把包带顶回去，管钳从腰后抽出来，锯齿从下往上撩，砸在那东西后颈。头骨塌进去一块，黑血顺着脊梁淌下来。";
  const baseline = `开头。\n\n${old}\n\n结尾。`;
  const current = `开头。\n\n${next}\n\n结尾。`;
  const onDecision = vi.fn().mockResolvedValue(undefined);
  const onChange = vi.fn();
  const props = { onClose: vi.fn(), onContentDiffDecision: onDecision, onContentDiffChange: onChange };
  const node = { id: "unrelated-chapter", type: "chapter", label: "章节", content: current, extra_data: {} };
  const { rerender } = render(<NodeDetailDrawer {...props} node={node}
    contentDiff={{ grouping: "agent_replacements", original_content: baseline, current_content: current,
      hunks: [{ start_offset: 0, old_text: baseline, new_text: current }] }} />);
  expect(screen.getAllByRole("button", { name: "撤回修改" })).toHaveLength(2);
  const insertion = screen.getByTestId("inline-diff-new").closest('[data-testid="inline-diff-hunk"]');
  expect(within(insertion).queryByTestId("inline-diff-old")).toBeNull();
  fireEvent.click(within(insertion).getByRole("button", { name: "撤回修改" }));
  await waitFor(() => expect(onDecision).toHaveBeenCalledWith(node.id, expect.objectContaining({
    expected_baseline: baseline, baseline_content: baseline, current_content: "开头。\n\n结尾。",
  })));
  await waitFor(() => expect(onChange).toHaveBeenCalled());
  rerender(<NodeDetailDrawer {...props} node={{ ...node, content: "开头。\n\n结尾。" }} contentDiff={onChange.mock.calls.at(-1)[0]} />);
  expect(screen.getAllByRole("button", { name: "撤回修改" })).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "撤回修改" }));
  await waitFor(() => expect(onDecision).toHaveBeenLastCalledWith(node.id, expect.objectContaining({
    baseline_content: baseline, current_content: baseline,
  })));
});
