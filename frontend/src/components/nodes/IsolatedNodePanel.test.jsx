import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
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
  it("只列出孤立节点，不列出画布上的结构节点", () => {
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

  it("没有孤立节点时不渲染任何分组", () => {
    render(<IsolatedNodePanel nodes={[node("o1", "outline", "大纲", "local")]} />);
    expect(screen.queryByText(/世界观/)).toBeNull();
    expect(screen.getByText("暂无全局节点")).toBeDefined();
  });

  it("配角不算孤立节点", () => {
    const withNpc = [...nodes, node("npc", "character", "配角甲", "minor")];
    render(<IsolatedNodePanel nodes={withNpc} />);
    expect(screen.queryByText("配角甲")).toBeNull();
  });

  it("空节点列表不报错", () => {
    render(<IsolatedNodePanel nodes={[]} />);
    expect(screen.getByText("暂无全局节点")).toBeDefined();
  });
});
