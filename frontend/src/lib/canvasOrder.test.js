import { describe, it, expect } from "vitest";
import { siblingOrderKey, compareSiblings, sortSiblings } from "./canvasOrder";

const node = (id, overrides = {}) => ({
  id,
  position: { x: 0, y: 0 },
  data: { type: "chapter", label: id, extra_data: {}, layer: 0, ...overrides.data },
  ...overrides,
});

describe("siblingOrderKey", () => {
  it("优先使用 extra_data 中的显式序号", () => {
    const key = siblingOrderKey(
      node("a", { data: { extra_data: { chapter_number: 3 } } }),
    );
    expect(key[0]).toBe(0);
    expect(key[1]).toBe(3);
  });

  it("识别 chapter_index / order / sequence 别名", () => {
    for (const field of ["chapter_index", "order", "sequence"]) {
      const key = siblingOrderKey(
        node("a", { data: { extra_data: { [field]: 7 } } }),
      );
      expect(key[1]).toBe(7);
    }
  });

  it("显式序号为数字字符串时同样生效", () => {
    const key = siblingOrderKey(
      node("a", { data: { extra_data: { chapter_number: "12" } } }),
    );
    expect(key[0]).toBe(0);
    expect(key[1]).toBe(12);
  });

  it("没有显式序号时解析标题中的章号", () => {
    const key = siblingOrderKey(node("a", { data: { label: "第 12 章 决战" } }));
    expect(key[0]).toBe(0);
    expect(key[1]).toBe(12);
  });

  it("标题与序号都缺失时退到 layer / x / 创建时间 / id", () => {
    const key = siblingOrderKey(node("a", { data: { label: "无编号" } }));
    expect(key[0]).toBe(1);
  });

  it("完全没有可用字段时仍返回确定性结果", () => {
    const bare = { id: "z", data: {} };
    const key = siblingOrderKey(bare);
    expect(Array.isArray(key)).toBe(true);
    expect(siblingOrderKey(bare)).toEqual(key);
  });
});

describe("compareSiblings", () => {
  it("显式序号小的排前面", () => {
    const a = node("a", { data: { extra_data: { chapter_number: 1 } } });
    const b = node("b", { data: { extra_data: { chapter_number: 2 } } });
    expect(compareSiblings(a, b)).toBeLessThan(0);
    expect(compareSiblings(b, a)).toBeGreaterThan(0);
  });

  it("有编号的节点排在无编号节点之前", () => {
    const numbered = node("a", { data: { label: "第 1 章" } });
    const plain = node("b", { data: { label: "杂项" } });
    expect(compareSiblings(numbered, plain)).toBeLessThan(0);
  });

  it("同为无编号时按创建时间排序", () => {
    const early = node("a", { data: { label: "甲", created_at: "2024-01-01T00:00:00" } });
    const late = node("b", { data: { label: "乙", created_at: "2024-06-01T00:00:00" } });
    expect(compareSiblings(early, late)).toBeLessThan(0);
  });

  it("创建时间也缺失时按 id 排序，保证结果确定", () => {
    const a = node("aaa", { data: { label: "甲" } });
    const b = node("bbb", { data: { label: "乙" } });
    expect(compareSiblings(a, b)).toBeLessThan(0);
    expect(compareSiblings(b, a)).toBeGreaterThan(0);
  });
});

describe("sortSiblings", () => {
  it("按章号升序排列", () => {
    const nodes = [
      node("c3", { data: { label: "第3章" } }),
      node("c1", { data: { label: "第1章" } }),
      node("c2", { data: { label: "第2章" } }),
    ];
    expect(sortSiblings(nodes).map((n) => n.id)).toEqual(["c1", "c2", "c3"]);
  });

  it("不修改入参数组", () => {
    const nodes = [
      node("c2", { data: { label: "第2章" } }),
      node("c1", { data: { label: "第1章" } }),
    ];
    sortSiblings(nodes);
    expect(nodes.map((n) => n.id)).toEqual(["c2", "c1"]);
  });

  it("缺少排序字段时多次调用结果一致", () => {
    const nodes = [node("x"), node("y"), node("z")].map((n) => ({
      ...n,
      data: { ...n.data, label: "无编号" },
    }));
    const first = sortSiblings(nodes).map((n) => n.id);
    const second = sortSiblings(nodes).map((n) => n.id);
    expect(first).toEqual(second);
  });
});
