import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import NodeDetailDrawer from "./NodeDetailDrawer";

describe("NodeDetailDrawer", () => {
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

  it("cycles through each occurrence of a character name in chapter content", () => {
    const addRange = vi.fn();
    const removeAllRanges = vi.fn();
    vi.spyOn(window, "getSelection").mockReturnValue({ addRange, removeAllRanges });
    render(
      <NodeDetailDrawer
        node={{
          id: "chapter-character-navigation",
          type: "chapter",
          label: "第一章",
          content: "林川看见林川。",
          extra_data: { characters: [{ id: "char-1", name: "林川" }] },
        }}
        onClose={vi.fn()}
      />,
    );

    const characterButton = screen.getByRole("button", { name: "定位角色：林川" });
    fireEvent.click(characterButton);
    fireEvent.click(characterButton);
    fireEvent.click(characterButton);

    expect(addRange.mock.calls.map(([range]) => range.startOffset)).toEqual([0, 4, 0]);
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
      getRangeAt: () => ({ commonAncestorContainer: selectedNode }),
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
      getRangeAt: () => ({ commonAncestorContainer: selectedNode }),
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
        node={{ id: "diff-history", type: "chapter", label: "第一章", content: "新文。", extra_data: {} }}
        contentDiff={{
          original_content: "旧文。",
          current_content: "新文。",
          hunks: [{ type: "replace", paragraph_index: 1, old_text: "旧文。", new_text: "新文。" }],
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
      expected_content: "新文。",
      expected_baseline: "新文。",
      baseline_content: "旧文。",
      current_content: "新文。",
    }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    fireEvent.keyDown(document, { key: "y", ctrlKey: true });
    await waitFor(() => expect(onContentDiffDecision).toHaveBeenNthCalledWith(3, "diff-history", {
      expected_content: "新文。",
      expected_baseline: "旧文。",
      baseline_content: "新文。",
      current_content: "新文。",
    }));
  });

  it("treats cancelling a diff as one undoable operation", async () => {
    const onContentDiffDecision = vi.fn().mockResolvedValue(undefined);
    render(
      <NodeDetailDrawer
        node={{ id: "reject-history", type: "chapter", label: "第一章", content: "新文。", extra_data: {} }}
        contentDiff={{
          original_content: "旧文。",
          current_content: "新文。",
          hunks: [{ type: "replace", paragraph_index: 1, old_text: "旧文。", new_text: "新文。" }],
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
      expected_content: "旧文。",
      expected_baseline: "旧文。",
      baseline_content: "旧文。",
      current_content: "新文。",
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

  it("keeps one submitted replacement indivisible in the frontend", () => {
    render(
      <NodeDetailDrawer
        node={{ id: "partial-inline", type: "chapter", label: "第一章", content: "甲新乙改丙", extra_data: {} }}
        contentDiff={{
          original_content: "甲旧乙旧丙",
          current_content: "甲新乙改丙",
          hunks: [{ type: "replace", paragraph_index: 1, old_text: "甲旧乙旧丙", new_text: "甲新乙改丙" }],
        }}
        onClose={vi.fn()}
        onContentDiffDecision={vi.fn()}
        onContentDiffChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("inline-diff-new").textContent).toBe("甲新乙改丙");
    expect(screen.getByTestId("inline-diff-new").querySelectorAll("[data-diff-kind]")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "查看替换前文本" })).toBeNull();
    expect(screen.queryByRole("button", { name: "删除新增文本" })).toBeNull();
  });

  it("keeps inserted text inside a replacement in the same submitted group", () => {
    render(
      <NodeDetailDrawer
        node={{ id: "remove-inline-insert", type: "chapter", label: "第一章", content: "甲新增乙新丙", extra_data: {} }}
        contentDiff={{
          original_content: "甲乙旧丙",
          current_content: "甲新增乙新丙",
          hunks: [{ type: "replace", paragraph_index: 1, old_text: "甲乙旧丙", new_text: "甲新增乙新丙" }],
        }}
        onClose={vi.fn()}
        onContentDiffDecision={vi.fn()}
        onContentDiffChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("inline-diff-new").textContent).toBe("甲新增乙新丙");
    expect(screen.queryByRole("button", { name: "删除新增文本" })).toBeNull();
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
    expect(screen.getByTestId("inline-diff-hunk")).toBeDefined();
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

    fireEvent.click(screen.getByRole("button", { name: "保留修改" }));

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

  it("keeps a multiline agent replacement as one group after a leading insertion", async () => {
    const old = "A\n\nB\n\nC";
    const next = "X\n\nA′\n\nB′\n\nC′";
    const onDecision = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer
      node={{ id: "grouped", type: "plot", label: "工具分组", content: next, extra_data: {} }}
      contentDiff={{ grouping: "agent_replacements", original_content: old, current_content: next,
        hunks: [{ type: "replace", paragraph_index: 1, start_offset: 0, old_text: old, new_text: next }] }}
      onContentDiffDecision={onDecision} onContentDiffChange={vi.fn()} onClose={vi.fn()}
    />);
    expect(screen.getAllByTestId("inline-diff-hunk")).toHaveLength(1);
    expect(screen.getByTestId("inline-diff-new").textContent.replaceAll("×", "")).toBe(next);
    fireEvent.click(screen.getByRole("button", { name: "撤回修改" }));
    await waitFor(() => expect(onDecision).toHaveBeenCalledWith("grouped", expect.objectContaining({
      baseline_content: old, current_content: old, groups: [],
    })));
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
    const { container } = render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(container.querySelector(".text-lg.leading-relaxed")).not.toBeNull();
    fireEvent.click(screen.getByTitle("全屏查看"));

    expect(container.querySelector(".text-xl.leading-loose")).not.toBeNull();
    expect(container.querySelector(".text-2xl")).not.toBeNull();
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
