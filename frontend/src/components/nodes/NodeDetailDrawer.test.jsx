import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import NodeDetailDrawer from "./NodeDetailDrawer";

describe("NodeDetailDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("exports a default component", () => {
    expect(NodeDetailDrawer).toBeDefined();
    expect(typeof NodeDetailDrawer).toBe("function");
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

    fireEvent.click(screen.getByTitle("编辑节点"));
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

  it("shows previous and next chapter buttons only in fullscreen chapter mode", () => {
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

    expect(screen.queryByTitle("下一章")).toBeNull();
    fireEvent.click(screen.getByTitle("全屏查看"));

    expect(screen.getByTitle("上一章").disabled).toBe(true);
    fireEvent.click(screen.getByTitle("下一章"));
    expect(onChapterNavigate).toHaveBeenCalledWith(chapters[1]);
  });

  it("enlarges chapter typography in fullscreen mode", () => {
    const node = { id: "large-chapter", type: "chapter", label: "第一章", content: "正文" };
    const { container } = render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(container.querySelector(".text-lg.leading-relaxed")).not.toBeNull();
    fireEvent.click(screen.getByTitle("全屏查看"));

    expect(container.querySelector(".text-xl.leading-loose")).not.toBeNull();
    expect(container.querySelector(".text-4xl")).not.toBeNull();
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

  it("renders a delete button when onDelete is provided", () => {
    const node = { id: "n1", type: "idea", label: "测试节点", content: "" };
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onDelete={vi.fn()} />);

    expect(screen.getByTitle("删除节点")).toBeDefined();
  });

  it("does not render a delete button when onDelete is not provided", () => {
    const node = { id: "n1", type: "idea", label: "测试节点", content: "" };
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} />);

    expect(screen.queryByTitle("删除节点")).toBeNull();
  });

  it("calls onDelete after user confirms", () => {
    const node = { id: "n1", type: "idea", label: "测试节点", content: "" };
    const onDelete = vi.fn();
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onDelete={onDelete} />);

    fireEvent.click(screen.getByTitle("删除节点"));

    expect(window.confirm).toHaveBeenCalled();
    expect(onDelete).toHaveBeenCalledWith(node);
  });

  it("does not call onDelete when user cancels confirmation", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const node = { id: "n1", type: "idea", label: "测试节点", content: "" };
    const onDelete = vi.fn();
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onDelete={onDelete} />);

    fireEvent.click(screen.getByTitle("删除节点"));

    expect(onDelete).not.toHaveBeenCalled();
  });

  it("enters edit mode and calls onUpdate with new title/content on save", async () => {
    const node = { id: "n1", type: "outline", label: "原标题", content: "原内容" };
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(<NodeDetailDrawer node={node} onClose={vi.fn()} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByTitle("编辑节点"));

    const titleInput = screen.getByDisplayValue("原标题");
    const contentArea = screen.getByDisplayValue("原内容");
    fireEvent.change(titleInput, { target: { value: "新标题" } });
    fireEvent.change(contentArea, { target: { value: "新内容" } });

    fireEvent.click(screen.getByText("保存"));

    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith("n1", { title: "新标题", content: "新内容" });
    });
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

    fireEvent.click(screen.getByTitle("编辑节点"));

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

    fireEvent.click(screen.getByTitle("编辑节点"));

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

    fireEvent.click(screen.getByTitle("编辑节点"));

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

    fireEvent.click(screen.getByTitle("编辑节点"));

    expect(screen.queryByText("添加元素")).toBeNull();
    expect(screen.queryByPlaceholderText("元素标题")).toBeNull();
  });
});
