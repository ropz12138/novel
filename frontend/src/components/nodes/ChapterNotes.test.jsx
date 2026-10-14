import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import NodeDetailDrawer from "./NodeDetailDrawer";
import { mergeRefreshedNodes } from "../../lib/canvasFlowAdapters";

describe("章节笔记", () => {
  it.each([false, true])("在章节详情展示完整笔记，appMode=%s", (appMode) => {
    const raw = { id: "chapter", type: "chapter", title: "第一章", content: "正文。", notes: "摘要：得到晶核。\n作者要求：保留伤势。\n设计：后续偿还。" };
    const flow = mergeRefreshedNodes([], [raw])[0];
    render(<NodeDetailDrawer appMode={appMode} node={{ id: flow.id, ...flow.data }} onClose={vi.fn()} />);
    expect(screen.getByText("章节笔记")).toBeDefined();
    expect(screen.getByTestId("chapter-notes").textContent).toContain("摘要：得到晶核。");
    expect(screen.getByTestId("chapter-notes").textContent).toContain("作者要求：保留伤势。");
    expect(screen.getByTestId("chapter-notes").textContent).toContain("设计：后续偿还。");
  });
  it("空笔记显示明确状态", () => {
    render(<NodeDetailDrawer node={{ id: "c", type: "chapter", content: "正文" }} onClose={vi.fn()} />);
    expect(screen.getByText("暂无章节笔记")).toBeDefined();
  });

  it("按 Markdown 渲染章节笔记", () => {
    render(<NodeDetailDrawer node={{
      id: "c",
      type: "chapter",
      content: "正文",
      notes: "## 连续性\n\n- 保留伤势\n- 核对晶核",
    }} onClose={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "连续性", level: 2 })).toBeDefined();
    expect(screen.getByTestId("chapter-notes").querySelectorAll("li")).toHaveLength(2);
  });

  it("编辑并保存章节笔记", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer node={{
      id: "c",
      type: "chapter",
      label: "第一章",
      content: "正文",
      notes: "原笔记",
    }} onClose={vi.fn()} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByTitle("编辑全文"));
    fireEvent.change(screen.getByLabelText("章节笔记（支持 Markdown）"), {
      target: { value: "## 新笔记\n\n- 新事实" },
    });
    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith("c", expect.objectContaining({
      notes: "## 新笔记\n\n- 新事实",
    })));
  });
});

it("刷新章节数据后展示新笔记", () => {
  const node = { id: "c", type: "chapter", content: "正文", notes: "原作者要求" };
  const { rerender } = render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);
  rerender(<NodeDetailDrawer node={{ ...node, notes: "更新后的作者要求" }} onClose={vi.fn()} />);
  expect(screen.getByTestId("chapter-notes").textContent).toBe("更新后的作者要求");
});
