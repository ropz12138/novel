import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import ExplorerPanel, { compareExplorerNodes, groupExplorerNodes } from "./ExplorerPanel";

const node = (id, type, label, extra = {}) => ({
  id,
  data: { type, label, sort_order: extra.sort_order ?? 0, scope: extra.scope, extra_data: extra.extra_data || {} },
});

describe("groupExplorerNodes", () => {
  it("按 sort_order 排列章节，并按角色 scope 分组", () => {
    const grouped = groupExplorerNodes([
      node("c2", "chapter", "第二章", { sort_order: 2 }),
      node("c1", "chapter", "第一章", { sort_order: 1 }),
      node("hero", "character", "林舟", { scope: "global" }),
      node("side", "character", "阿青", { scope: "minor" }),
      node("world", "worldbuilding", "灵气体系"),
      node("note", "note", "写作要求"),
      node("review", "reviewer_note", "评审意见"),
    ]);
    expect(grouped.chapter.map((item) => item.id)).toEqual(["c1", "c2"]);
    expect(grouped.character.find((group) => group.scope === "global").items.map((item) => item.id)).toEqual(["hero"]);
    expect(grouped.character.find((group) => group.scope === "minor").items.map((item) => item.id)).toEqual(["side"]);
    expect(grouped.worldbuilding[0].data.label).toBe("灵气体系");
    expect(grouped.note[0].data.label).toBe("写作要求");
    expect(grouped.reviewer_note[0].data.label).toBe("评审意见");
  });

  it("compareExplorerNodes 在顺序相同时按标题排序", () => {
    expect(compareExplorerNodes(
      node("b", "chapter", "B章", { sort_order: 1 }),
      node("a", "chapter", "A章", { sort_order: 1 }),
    )).toBeGreaterThan(0);
  });
});

describe("ExplorerPanel", () => {
  const nodes = [
    node("c2", "chapter", "第二章", { sort_order: 2 }),
    node("c1", "chapter", "第一章", { sort_order: 1 }),
    node("hero", "character", "林舟", { scope: "global" }),
    node("world", "worldbuilding", "灵气体系"),
    node("note", "note", "写作要求"),
    node("review", "reviewer_note", "评审意见"),
  ];

  it("列出章节、角色、世界观、笔记和评审笔记", () => {
    render(<ExplorerPanel nodes={nodes} />);
    expect(screen.getByRole("button", { name: "第一章" })).toBeDefined();
    expect(screen.getByRole("button", { name: "第二章" })).toBeDefined();
    expect(screen.getByRole("button", { name: "林舟" })).toBeDefined();
    expect(screen.getByText("主角 1")).toBeDefined();
    expect(screen.getByRole("button", { name: "灵气体系" })).toBeDefined();
    expect(screen.getByRole("button", { name: "写作要求" })).toBeDefined();
    expect(screen.getByRole("button", { name: "评审意见" })).toBeDefined();
  });

  it("点击条目会选中对应节点", () => {
    const onSelect = vi.fn();
    render(<ExplorerPanel nodes={nodes} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: "第一章" }));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: "c1", type: "chapter", label: "第一章" }),
      expect.any(Object),
    );
  });

  it("各分组提供添加入口", () => {
    const onAdd = vi.fn();
    render(<ExplorerPanel nodes={[]} onAdd={onAdd} />);
    fireEvent.click(screen.getByRole("button", { name: "添加章节" }));
    fireEvent.click(screen.getByRole("button", { name: "添加角色" }));
    fireEvent.click(screen.getByRole("button", { name: "添加世界观" }));
    fireEvent.click(screen.getByRole("button", { name: "添加笔记" }));
    fireEvent.click(screen.getByRole("button", { name: "添加评审笔记" }));
    expect(onAdd.mock.calls.map((call) => call[0])).toEqual([
      "chapter",
      "character",
      "worldbuilding",
      "note",
      "reviewer_note",
    ]);
  });

  it("拖拽章节后回调整后的顺序", () => {
    const onReorderChapters = vi.fn();
    render(<ExplorerPanel nodes={nodes} onReorderChapters={onReorderChapters} />);
    fireEvent.dragStart(screen.getByTestId("explorer-item-c2"), {
      dataTransfer: { setData: vi.fn(), effectAllowed: "move" },
    });
    const first = screen.getByTestId("explorer-item-c1");
    fireEvent.dragOver(first);
    fireEvent.drop(first, { dataTransfer: { getData: () => "c2" } });
    expect(onReorderChapters).toHaveBeenCalledWith(["c2", "c1"]);
  });

  it("右键可以复制或删除节点", () => {
    const onCopyNode = vi.fn();
    const onDeleteNode = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<ExplorerPanel nodes={nodes} onCopyNode={onCopyNode} onDeleteNode={onDeleteNode} />);
    fireEvent.contextMenu(screen.getByRole("button", { name: "林舟" }));
    fireEvent.click(screen.getByRole("button", { name: "复制到其他作品" }));
    expect(onCopyNode).toHaveBeenCalledWith(expect.objectContaining({ id: "hero" }));

    fireEvent.contextMenu(screen.getByRole("button", { name: "写作要求" }));
    fireEvent.click(screen.getByRole("button", { name: "删除节点" }));
    expect(onDeleteNode).toHaveBeenCalledWith(expect.objectContaining({ id: "note", type: "note" }));
  });
});
