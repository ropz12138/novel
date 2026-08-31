import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  VIEW_STATE_VERSION,
  viewStateStorageKey,
  loadViewState,
  saveViewState,
  clearViewState,
  pruneExpandedIds,
} from "./canvasViewState";

function memoryStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, value),
    removeItem: (key) => map.delete(key),
    _map: map,
  };
}

describe("viewStateStorageKey", () => {
  it("按作品分键，避免不同作品互相污染", () => {
    expect(viewStateStorageKey("w1")).not.toBe(viewStateStorageKey("w2"));
    expect(viewStateStorageKey("w1")).toContain("w1");
  });
});

describe("saveViewState / loadViewState", () => {
  let storage;

  beforeEach(() => {
    storage = memoryStorage();
  });

  it("写入后可原样读回展开集合与 viewport", () => {
    saveViewState(
      "w1",
      {
        expandedNodeIds: new Set(["a", "b"]),
        viewport: { x: 12, y: -34, zoom: 0.75 },
      },
      storage,
    );

    const loaded = loadViewState("w1", storage);
    expect(loaded.expandedNodeIds).toEqual(new Set(["a", "b"]));
    expect(loaded.viewport).toEqual({ x: 12, y: -34, zoom: 0.75 });
  });

  it("接受数组形式的展开集合", () => {
    saveViewState("w1", { expandedNodeIds: ["a"], viewport: null }, storage);
    expect(loadViewState("w1", storage).expandedNodeIds).toEqual(new Set(["a"]));
  });

  it("写入内容带版本号", () => {
    saveViewState("w1", { expandedNodeIds: new Set(), viewport: null }, storage);
    const raw = JSON.parse(storage.getItem(viewStateStorageKey("w1")));
    expect(raw.version).toBe(VIEW_STATE_VERSION);
  });

  it("没有记录时返回 null", () => {
    expect(loadViewState("w1", storage)).toBeNull();
  });

  it("缺少 workId 时不读不写", () => {
    saveViewState(null, { expandedNodeIds: new Set(["a"]), viewport: null }, storage);
    expect(storage._map.size).toBe(0);
    expect(loadViewState(null, storage)).toBeNull();
  });

  it("版本号不匹配时丢弃记录", () => {
    const stale = memoryStorage({
      [viewStateStorageKey("w1")]: JSON.stringify({
        version: VIEW_STATE_VERSION + 1,
        expanded_node_ids: ["a"],
        viewport: { x: 0, y: 0, zoom: 1 },
      }),
    });
    expect(loadViewState("w1", stale)).toBeNull();
  });

  it("内容损坏时丢弃记录而不抛错", () => {
    const broken = memoryStorage({
      [viewStateStorageKey("w1")]: "{not json",
    });
    expect(loadViewState("w1", broken)).toBeNull();
  });

  it("viewport 字段非法时只丢弃 viewport，保留展开集合", () => {
    const partial = memoryStorage({
      [viewStateStorageKey("w1")]: JSON.stringify({
        version: VIEW_STATE_VERSION,
        expanded_node_ids: ["a"],
        viewport: { x: "left", y: 0, zoom: 1 },
      }),
    });
    const loaded = loadViewState("w1", partial);
    expect(loaded.expandedNodeIds).toEqual(new Set(["a"]));
    expect(loaded.viewport).toBeNull();
  });

  it("展开集合不是数组时视为空集", () => {
    const partial = memoryStorage({
      [viewStateStorageKey("w1")]: JSON.stringify({
        version: VIEW_STATE_VERSION,
        expanded_node_ids: "a,b",
        viewport: null,
      }),
    });
    expect(loadViewState("w1", partial).expandedNodeIds).toEqual(new Set());
  });

  it("storage 不可用时静默跳过", () => {
    const failing = {
      getItem: vi.fn(() => {
        throw new Error("SecurityError");
      }),
      setItem: vi.fn(() => {
        throw new Error("QuotaExceededError");
      }),
      removeItem: vi.fn(),
    };
    expect(loadViewState("w1", failing)).toBeNull();
    expect(() =>
      saveViewState("w1", { expandedNodeIds: new Set(["a"]), viewport: null }, failing),
    ).not.toThrow();
  });
});

describe("clearViewState", () => {
  it("删除指定作品的记录", () => {
    const storage = memoryStorage();
    saveViewState("w1", { expandedNodeIds: new Set(["a"]), viewport: null }, storage);
    clearViewState("w1", storage);
    expect(loadViewState("w1", storage)).toBeNull();
  });
});

describe("pruneExpandedIds", () => {
  it("剔除已不存在的节点，避免记录无限增长", () => {
    const pruned = pruneExpandedIds(new Set(["a", "gone"]), new Set(["a", "b"]));
    expect(pruned).toEqual(new Set(["a"]));
  });

  it("全部存在时返回等价集合", () => {
    expect(pruneExpandedIds(new Set(["a"]), new Set(["a", "b"]))).toEqual(
      new Set(["a"]),
    );
  });

  it("节点集合为空时返回空集", () => {
    expect(pruneExpandedIds(new Set(["a"]), new Set())).toEqual(new Set());
  });
});
