import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import IsolatedNodePanel from "./IsolatedNodePanel";

const node = (id, type, label, scope = "global") => ({
  id,
  data: { type, label, scope, content: "", extra_data: {} },
});

const nodes = [
  node("o1", "outline", "大纲", "local"),
  node("c1", "chapter", "第一章", "local"),
  node("hero", "character", "林川"),
  node("w1", "worldbuilding", "灵气体系"),
  node("w2", "worldbuilding", "地理"),
  node("n1", "note", "灵感"),
];

describe("IsolatedNodePanel", () => {
  it("shows dedicated reviewer notes separately and opens them for editing", () => {
    const onSelect = vi.fn();
    render(<IsolatedNodePanel nodes={[node("review", "reviewer_note", "本作评审要求")]} onSelect={onSelect} />);
    expect(screen.getByText("评审笔记 1")).toBeDefined();
    fireEvent.click(screen.getByText("本作评审要求"));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "review", type: "reviewer_note" }));
  });
  it("只列出非层级链节点，不列出画布上的结构节点", () => {
    render(<IsolatedNodePanel nodes={nodes} />);
    expect(screen.getByText("灵气体系")).toBeDefined();
    expect(screen.getByText("林川")).toBeDefined();
    expect(screen.queryByText("大纲")).toBeNull();
    expect(screen.queryByText("第一章")).toBeNull();
  });

  it("按类型分组并显示数量", () => {
    render(<IsolatedNodePanel nodes={nodes} />);
    expect(screen.getByText("世界观 2")).toBeDefined();
    expect(screen.getByText("笔记 1")).toBeDefined();
    expect(screen.getByText("主角 1")).toBeDefined();
  });

  it("点击条目回调对应节点", () => {
    const onSelect = vi.fn();
    render(<IsolatedNodePanel nodes={nodes} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("灵气体系"));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: "w1", label: "灵气体系" }),
    );
  });

  it("右键笔记、角色和世界观后可以选择复制到其他作品", () => {
    const onSelect = vi.fn();
    const onCopyNode = vi.fn();
    render(<IsolatedNodePanel nodes={nodes} onSelect={onSelect} onCopyNode={onCopyNode} />);

    fireEvent.contextMenu(screen.getByRole("button", { name: "灵感" }));
    fireEvent.click(screen.getByRole("button", { name: "复制到其他作品" }));
    fireEvent.contextMenu(screen.getByRole("button", { name: "灵气体系" }));
    fireEvent.click(screen.getByRole("button", { name: "复制到其他作品" }));
    fireEvent.contextMenu(screen.getByRole("button", { name: "林川" }));
    fireEvent.click(screen.getByRole("button", { name: "复制到其他作品" }));

    expect(onCopyNode).toHaveBeenNthCalledWith(1, expect.objectContaining({ id: "n1", data: expect.objectContaining({ type: "note" }) }));
    expect(onCopyNode).toHaveBeenNthCalledWith(2, expect.objectContaining({ id: "w1", data: expect.objectContaining({ type: "worldbuilding" }) }));
    expect(onCopyNode).toHaveBeenNthCalledWith(3, expect.objectContaining({ id: "hero", data: expect.objectContaining({ type: "character" }) }));
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("左键只打开节点，不弹出复制菜单", () => {
    render(<IsolatedNodePanel nodes={nodes} onCopyNode={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "林川" }));
    expect(screen.queryByRole("button", { name: "复制到其他作品" })).toBeNull();
  });

  it("App 里长按会打开复制菜单，松手后的点击不进入详情", () => {
    vi.useFakeTimers();
    try {
      const onSelect = vi.fn();
      render(<IsolatedNodePanel nodes={nodes} onSelect={onSelect} onCopyNode={vi.fn()} appMode />);
      const row = screen.getByRole("button", { name: "灵感" });
      fireEvent.mouseDown(row, { clientX: 20, clientY: 30 });
      act(() => {
        vi.advanceTimersByTime(500);
      });
      expect(screen.getByRole("button", { name: "复制到其他作品" })).toBeDefined();
      fireEvent.mouseUp(row);
      fireEvent.click(row);
      expect(onSelect).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("没有可列出的节点时不渲染任何分组", () => {
    render(<IsolatedNodePanel nodes={[node("o1", "outline", "大纲", "local")]} />);
    expect(screen.queryByText(/世界观/)).toBeNull();
    expect(screen.getByText("暂无角色或设定")).toBeDefined();
  });

  it("配角也有侧栏入口，按角色分类分组", () => {
    const withNpcs = [
      ...nodes,
      node("npc1", "character", "配角甲", "major"),
      node("npc2", "character", "配角乙", "major"),
      node("npc3", "character", "路人", "minor"),
      node("npc4", "character", "临时角色", "temp"),
    ];
    render(<IsolatedNodePanel nodes={withNpcs} />);

    expect(screen.getByText("配角甲")).toBeDefined();
    expect(screen.getByText("路人")).toBeDefined();
    expect(screen.getByText("主要配角 2")).toBeDefined();
    expect(screen.getByText("次要配角 1")).toBeDefined();
    expect(screen.getByText("临时角色 1")).toBeDefined();
    // 主角与配角分开列出，不混在同一组
    expect(screen.getByText("主角 1")).toBeDefined();
  });

  it("空分类不渲染标题", () => {
    render(<IsolatedNodePanel nodes={[node("hero", "character", "林川")]} />);
    expect(screen.queryByText(/主要配角/)).toBeNull();
    expect(screen.queryByText(/笔记/)).toBeNull();
  });

  it("空节点列表不报错", () => {
    render(<IsolatedNodePanel nodes={[]} />);
    expect(screen.getByText("暂无角色或设定")).toBeDefined();
  });

  it("可以独立收起和展开角色与设定侧栏", () => {
    render(<IsolatedNodePanel nodes={nodes} />);

    fireEvent.click(screen.getByRole("button", { name: "收起角色与设定侧栏" }));
    expect(screen.queryByText("林川")).toBeNull();
    expect(screen.getByRole("button", { name: "展开角色与设定侧栏" })).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "展开角色与设定侧栏" }));
    expect(screen.getByText("林川")).toBeDefined();
    expect(screen.getByRole("button", { name: "收起角色与设定侧栏" })).toBeDefined();
  });

  it("支持为 App 设置初始收起状态", () => {
    render(<IsolatedNodePanel nodes={nodes} initialCollapsed />);

    expect(screen.queryByText("林川")).toBeNull();
    expect(screen.getByRole("button", { name: "展开角色与设定侧栏" })).toBeDefined();
  });

  it("展开时叠在节点详情之上", () => {
    render(<IsolatedNodePanel nodes={nodes} />);
    expect(screen.getByTestId("isolated-node-panel").className).toContain("z-[55]");
  });

  it("App 模式为底部悬浮输入框预留滚动空间", () => {
    render(<IsolatedNodePanel nodes={nodes} appMode />);

    expect(screen.getByTestId("isolated-node-panel").className)
      .toContain("pb-[calc(7rem+env(safe-area-inset-bottom))]");
  });

});
