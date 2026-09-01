import { describe, it, expect } from "vitest";
import {
  siblingOrderKey,
  compareSiblings,
  sortSiblings,
  nextSortOrder,
} from "./canvasOrder";

const node = (id, overrides = {}) => ({
  id,
  position: { x: 0, y: 0 },
  data: { type: "chapter", label: id, sort_order: 0, ...overrides.data },
  ...overrides,
});

describe("siblingOrderKey", () => {
  it("使用节点的 sort_order", () => {
    expect(siblingOrderKey(node("a", { data: { sort_order: 3 } }))[0]).toBe(3);
  });

  it("忽略标题中的章号", () => {
    const key = siblingOrderKey(
      node("a", { data: { sort_order: 1, label: "第 12 章 决战" } }),
    );
    expect(key[0]).toBe(1);
  });

  it("忽略 extra_data 中的历史序号字段", () => {
    const key = siblingOrderKey(
      node("a", { data: { sort_order: 1, extra_data: { chapter_number: 42 } } }),
    );
    expect(key[0]).toBe(1);
  });

  it("sort_order 缺失时返回确定性结果", () => {
    const bare = { id: "z", data: {} };
    expect(siblingOrderKey(bare)).toEqual(siblingOrderKey(bare));
  });
});

describe("compareSiblings", () => {
  it("sort_order 小的排前面", () => {
    const a = node("a", { data: { sort_order: 1 } });
    const b = node("b", { data: { sort_order: 2 } });
    expect(compareSiblings(a, b)).toBeLessThan(0);
    expect(compareSiblings(b, a)).toBeGreaterThan(0);
  });

  it("sort_order 并列时按 id 排序，保证结果确定", () => {
    const a = node("aaa", { data: { sort_order: 1 } });
    const b = node("bbb", { data: { sort_order: 1 } });
    expect(compareSiblings(a, b)).toBeLessThan(0);
    expect(compareSiblings(b, a)).toBeGreaterThan(0);
  });

  it("顺序与标题无关", () => {
    const first = node("a", { data: { sort_order: 1, label: "第 9 章" } });
    const second = node("b", { data: { sort_order: 2, label: "第 1 章" } });
    expect(compareSiblings(first, second)).toBeLessThan(0);
  });
});

describe("sortSiblings", () => {
  it("按 sort_order 升序排列", () => {
    const nodes = [
      node("c3", { data: { sort_order: 3 } }),
      node("c1", { data: { sort_order: 1 } }),
      node("c2", { data: { sort_order: 2 } }),
    ];
    expect(sortSiblings(nodes).map((n) => n.id)).toEqual(["c1", "c2", "c3"]);
  });

  it("不修改入参数组", () => {
    const nodes = [
      node("c2", { data: { sort_order: 2 } }),
      node("c1", { data: { sort_order: 1 } }),
    ];
    sortSiblings(nodes);
    expect(nodes.map((n) => n.id)).toEqual(["c2", "c1"]);
  });

  it("sort_order 全部相同时多次调用结果一致", () => {
    const nodes = [node("x"), node("y"), node("z")];
    expect(sortSiblings(nodes).map((n) => n.id)).toEqual(
      sortSiblings(nodes).map((n) => n.id),
    );
  });
});

describe("nextSortOrder", () => {
  const typed = (id, type, sort_order) => ({ id, data: { type, sort_order } });

  it("排在同类型节点之后", () => {
    const nodes = [
      typed("a", "chapter", 1),
      typed("b", "chapter", 5),
      typed("c", "chapter", 3),
    ];
    expect(nextSortOrder(nodes, "chapter")).toBe(6);
  });

  it("只看同类型节点，不受其它类型影响", () => {
    const nodes = [typed("a", "volume", 99), typed("b", "chapter", 2)];
    expect(nextSortOrder(nodes, "chapter")).toBe(3);
  });

  it("该类型还没有节点时从 1 开始", () => {
    expect(nextSortOrder([typed("a", "volume", 4)], "chapter")).toBe(1);
    expect(nextSortOrder([], "chapter")).toBe(1);
  });

  it("忽略 sort_order 缺失的节点", () => {
    const nodes = [typed("a", "chapter", undefined), typed("b", "chapter", 2)];
    expect(nextSortOrder(nodes, "chapter")).toBe(3);
  });
});
