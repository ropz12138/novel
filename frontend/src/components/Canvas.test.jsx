import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";

const mocks = vi.hoisted(() => ({
  nodes: [],
  setNodes: vi.fn(),
  edges: [],
  setEdges: vi.fn(),
  lastReactFlowProps: null,
  customNodeProps: [],
  fitView: vi.fn(),
}));

vi.mock("@xyflow/react", async () => {
  const React = await import("react");
  return {
    ReactFlow: (props) => {
      mocks.lastReactFlowProps = props;
      return React.createElement(
        "div",
        { "data-testid": "react-flow", className: "react-flow" },
        props.children,
      );
    },
    ReactFlowProvider: ({ children }) => children,
    Background: () => null,
    Controls: () => <div data-testid="flow-controls" />,
    MiniMap: () => <div data-testid="flow-minimap" />,
    addEdge: (edge, edges) => [...edges, edge],
    useNodesState: () => [mocks.nodes, mocks.setNodes, vi.fn()],
    useEdgesState: () => [mocks.edges, mocks.setEdges, vi.fn()],
    MarkerType: { ArrowClosed: "arrowclosed" },
    useReactFlow: () => ({ fitView: mocks.fitView }),
  };
});

vi.mock("./nodes/CustomNode", () => ({
  default: (props) => {
    mocks.customNodeProps.push(props);
    return null;
  },
}));

vi.mock("./nodes/NodeDetailDrawer", () => ({
  default: () => null,
}));

vi.mock("../lib/canvasApi", () => ({
  fetchNodes: vi.fn(),
  fetchEdges: vi.fn(),
  createNode: vi.fn(),
  updateNode: vi.fn(),
  createEdge: vi.fn(),
  deleteEdge: vi.fn(),
  deleteNode: vi.fn(),
  copyNodeToWork: vi.fn(),
  restoreCanvasSnapshot: vi.fn(),
}));

import { Canvas, mergeRefreshedNodes, toCanvasSnapshot, applyNodeUpdateToData } from "./Canvas";

function installMatchMedia() {
  window.matchMedia = (query) => ({
    media: query,
    matches: false,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  });
}

beforeEach(() => {
  installMatchMedia();
});

afterEach(() => {
  vi.useRealTimers();
});

import {
  fetchNodes,
  fetchEdges,
  deleteNode,
  copyNodeToWork,
  restoreCanvasSnapshot,
  updateNode,
} from "../lib/canvasApi";

describe("toCanvasSnapshot", () => {
  it("serializes complete node and edge state", () => {
    expect(toCanvasSnapshot(
      [{
        id: "n1",
        position: { x: 12, y: 34 },
        data: {
          type: "chapter",
          label: "第一章",
          content: "正文",
          notes: "摘要与作者要求",
          extra_data: { a: 1 },
          layer: 2,
          sort_order: 3,
          scope: "global",
        },
      }],
      [{
        id: "e1",
        source: "n1",
        target: "n2",
        label: "推进",
        data: { edge_type: "本章推进", extra_data: { b: 2 } },
      }]
    )).toEqual({
      nodes: [{
        id: "n1",
        type: "chapter",
        title: "第一章",
        content: "正文",
          notes: "摘要与作者要求",
        extra_data: { a: 1 },
        layer: 2,
        sort_order: 3,
        scope: "global",
        position_x: 12,
        position_y: 34,
      }],
      edges: [{
        id: "e1",
        source_id: "n1",
        target_id: "n2",
        edge_type: "本章推进",
        label: "推进",
        extra_data: { b: 2 },
      }],
    });
  });

  it("defaults scope to local when missing in node data", () => {
    const snap = toCanvasSnapshot(
      [{
        id: "n1",
        position: { x: 0, y: 0 },
        data: { type: "character", label: "A", content: "", extra_data: {}, layer: 0 },
      }],
      []
    );
    expect(snap.nodes[0].scope).toBe("local");
  });
});

// 父子关系判定与收起子树的测试见 lib/canvasRelation.test.js 与 lib/canvasGraph.test.js，
// 判定依据已由自然语言 edge_type 改为节点类型。

// ── 纯函数 mergeRefreshedNodes 测试 ──

describe("mergeRefreshedNodes", () => {
  it("preserves existing node position when refreshing", () => {
    const currentNodes = [
      {
        id: "n1",
        type: "custom",
        position: { x: 100, y: 200 },
        data: { type: "idea", label: "旧标题", content: "旧内容" },
      },
    ];
    const fetchedRaw = [
      {
        id: "n1",
        type: "idea",
        title: "新标题",
        content: "新内容",
        extra_data: null,
        position_x: 999,
        position_y: 888,
      },
    ];
    const result = mergeRefreshedNodes(currentNodes, fetchedRaw);
    expect(result).toHaveLength(1);
    expect(result[0].position).toEqual({ x: 999, y: 888 });
    expect(result[0].data.label).toBe("新标题");
    expect(result[0].data.content).toBe("新内容");
  });

  it("uses database position for new nodes", () => {
    const currentNodes = [];
    const fetchedRaw = [
      {
        id: "n1",
        type: "idea",
        title: "新节点",
        content: "内容",
        extra_data: null,
        position_x: 50,
        position_y: 60,
      },
    ];
    const result = mergeRefreshedNodes(currentNodes, fetchedRaw);
    expect(result).toHaveLength(1);
    expect(result[0].position).toEqual({ x: 50, y: 60 });
  });

  it("assigns fixed dimensions from node type", () => {
    const result = mergeRefreshedNodes([], [
      {
        id: "e1",
        type: "element",
        title: "元素",
        content: "",
        extra_data: null,
        position_x: 0,
        position_y: 0,
      },
      {
        id: "c1",
        type: "chapter",
        title: "章",
        content: "",
        extra_data: null,
        position_x: 100,
        position_y: 0,
      },
    ]);
    expect(result[0].width).toBe(90);
    expect(result[0].height).toBe(90);
    expect(result[1].width).toBe(250);
    expect(result[1].height).toBe(120);
  });

  it("removes deleted nodes (not present in fetched data)", () => {
    const currentNodes = [
      {
        id: "n1",
        type: "custom",
        position: { x: 10, y: 20 },
        data: { type: "idea", label: "A", content: "" },
      },
      {
        id: "n2",
        type: "custom",
        position: { x: 30, y: 40 },
        data: { type: "idea", label: "B", content: "" },
      },
    ];
    const fetchedRaw = [
      {
        id: "n1",
        type: "idea",
        title: "A",
        content: "",
        extra_data: null,
        position_x: 10,
        position_y: 20,
      },
    ];
    const result = mergeRefreshedNodes(currentNodes, fetchedRaw);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("n1");
  });

  it("handles empty fetched data", () => {
    const currentNodes = [
      {
        id: "n1",
        type: "custom",
        position: { x: 10, y: 20 },
        data: { type: "idea", label: "A", content: "" },
      },
    ];
    const result = mergeRefreshedNodes(currentNodes, []);
    expect(result).toEqual([]);
  });

  it("updates extra_data for existing nodes", () => {
    const currentNodes = [
      {
        id: "n1",
        type: "custom",
        position: { x: 10, y: 20 },
        data: { type: "idea", label: "A", content: "", extra_data: null },
      },
    ];
    const fetchedRaw = [
      {
        id: "n1",
        type: "idea",
        title: "A",
        content: "",
        extra_data: { custom: "data" },
        position_x: 10,
        position_y: 20,
      },
    ];
    const result = mergeRefreshedNodes(currentNodes, fetchedRaw);
    expect(result[0].data.extra_data).toEqual({ custom: "data" });
  });

  it("preserves position while updating data.type", () => {
    const currentNodes = [
      {
        id: "n1",
        type: "custom",
        position: { x: 100, y: 200 },
        data: { type: "idea", label: "旧", content: "" },
      },
    ];
    const fetchedRaw = [
      {
        id: "n1",
        type: "chapter",
        title: "新",
        content: "updated",
        extra_data: null,
        position_x: 0,
        position_y: 0,
      },
    ];
    const result = mergeRefreshedNodes(currentNodes, fetchedRaw);
    expect(result[0].position).toEqual({ x: 0, y: 0 });
    expect(result[0].data.type).toBe("chapter");
  });

  it("handles mix of existing, new, and deleted nodes", () => {
    const currentNodes = [
      {
        id: "n1",
        type: "custom",
        position: { x: 10, y: 20 },
        data: { type: "idea", label: "A", content: "old" },
      },
      {
        id: "n2",
        type: "custom",
        position: { x: 30, y: 40 },
        data: { type: "idea", label: "B", content: "old" },
      },
    ];
    const fetchedRaw = [
      {
        id: "n1",
        type: "idea",
        title: "A",
        content: "new",
        extra_data: null,
        position_x: 999,
        position_y: 999,
      },
      {
        id: "n3",
        type: "chapter",
        title: "C",
        content: "brand new",
        extra_data: null,
        position_x: 50,
        position_y: 60,
      },
    ];
    const result = mergeRefreshedNodes(currentNodes, fetchedRaw);
    expect(result).toHaveLength(2);
    const n1 = result.find((n) => n.id === "n1");
    expect(n1.position).toEqual({ x: 999, y: 999 });
    expect(n1.data.content).toBe("new");
    const n3 = result.find((n) => n.id === "n3");
    expect(n3.position).toEqual({ x: 50, y: 60 });
    expect(result.find((n) => n.id === "n2")).toBeUndefined();
  });

  it("passes scope from fetched data into node data (default local)", () => {
    const fetchedRaw = [
      {
        id: "n1",
        type: "character",
        title: "主角",
        content: "",
        extra_data: null,
        scope: "global",
        position_x: 0,
        position_y: 0,
      },
      {
        id: "n2",
        type: "character",
        title: "配角",
        content: "",
        extra_data: null,
        position_x: 10,
        position_y: 10,
      },
    ];
    const result = mergeRefreshedNodes([], fetchedRaw);
    expect(result[0].data.scope).toBe("global");
    // 缺省 scope 默认 local
    expect(result[1].data.scope).toBe("local");
  });
});

// ── 纯函数 applyNodeUpdateToData 测试 ──

describe("applyNodeUpdateToData", () => {
  it("maps title into label and updates content", () => {
    const prev = { label: "旧", content: "旧内容", extra_data: { a: 1 } };
    const next = applyNodeUpdateToData(prev, { title: "新", content: "新内容" });
    expect(next.label).toBe("新");
    expect(next.content).toBe("新内容");
    expect(next.extra_data).toEqual({ a: 1 });
  });

  it("updates chapter notes in local node data", () => {
    const prev = { label: "第一章", content: "正文", notes: "旧笔记", extra_data: {} };
    const next = applyNodeUpdateToData(prev, { notes: "## 新笔记" });
    expect(next.notes).toBe("## 新笔记");
  });

  it("ignores chapter_elements in node updates and keeps other extra_data", () => {
    const prev = {
      label: "x",
      content: "",
      extra_data: { last_generation: { ok: true }, chapter_elements: [{ id: "old" }] },
    };
    const next = applyNodeUpdateToData(prev, { chapter_elements: [{ id: "new" }] });
    expect(next.extra_data).toEqual(prev.extra_data);
    expect(next.extra_data.last_generation).toEqual({ ok: true });
  });

  it("merges characters into extra_data preserving other fields", () => {
    const prev = {
      label: "第一章",
      content: "",
      extra_data: {
        last_generation: { ok: true },
        characters: [{ id: "old", name: "旧" }],
      },
    };
    const next = applyNodeUpdateToData(prev, {
      characters: [{ id: "char-1", name: "林川" }],
    });
    expect(next.extra_data.characters).toEqual([{ id: "char-1", name: "林川" }]);
    expect(next.extra_data.last_generation).toEqual({ ok: true });
  });

  it("preserves label/content when title/content absent in update", () => {
    const prev = { label: "保留", content: "保留c", extra_data: {} };
    const next = applyNodeUpdateToData(prev, { notes: prev.notes });
    expect(next.label).toBe("保留");
    expect(next.content).toBe("保留c");
    expect(next.extra_data).toEqual({});
  });

  it("merges storylines into extra_data preserving other fields", () => {
    const prev = {
      label: "林川",
      content: "人设",
      extra_data: { last_generation: { ok: true }, storylines: [{ name: "旧" }] },
    };
    const next = applyNodeUpdateToData(prev, {
      storylines: [{ name: "力量线", description: "明线", body: ["觉醒"] }],
    });
    expect(next.extra_data.storylines[0].name).toBe("力量线");
    expect(next.extra_data.last_generation).toEqual({ ok: true });
  });

  it("returns prev unchanged when prev is null", () => {
    expect(applyNodeUpdateToData(null, { title: "x" })).toBeNull();
  });
});

// ── Canvas 组件集成测试 ──

describe("Canvas forwardRef", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.nodes = [];
    mocks.edges = [];
    mocks.lastReactFlowProps = null;
  });

  it("opens a node detail by node id through the imperative handle", async () => {
    mocks.nodes = [{
      id: "chapter-1",
      type: "custom",
      position: { x: 0, y: 0 },
      data: { type: "chapter", label: "第一章", content: "正文", notes: "笔记段", extra_data: {} },
    }];
    fetchNodes.mockResolvedValue({
      nodes: [{
        id: "chapter-1",
        type: "chapter",
        title: "第一章",
        content: "正文",
        notes: "笔记段",
        extra_data: {},
        position_x: 0,
        position_y: 0,
      }],
    });
    fetchEdges.mockResolvedValue({ edges: [] });
    const ref = createRef();

    render(<Canvas ref={ref} workId="w-open-detail" />);
    await waitFor(() => expect(ref.current).not.toBeNull());

    let opened;
    act(() => {
      opened = ref.current.openNodeDetail("chapter-1");
    });
    expect(opened).toBe(true);
    expect(ref.current.openNodeDetail("missing-node")).toBe(false);
    act(() => {
      expect(ref.current.openNodeDetail("chapter-1", "正文")).toBe(true);
    });
    act(() => {
      expect(ref.current.openNodeDetail("chapter-1", undefined, {
        field: "content", hunk: { type: "replace", paragraph_index: 1, new_text: "正文" },
      })).toBe(true);
    });
    const alert = vi.spyOn(window, "alert").mockImplementation(() => {});
    expect(ref.current.openNodeDetail("chapter-1", "已删除的文字")).toBe(false);
    expect(alert).toHaveBeenCalledWith("引用原文已变化或存在多处匹配，请让 AI 重新生成引用。");
    expect(ref.current.openNodeDetail("chapter-1", { startParagraph: 1, endParagraph: 1, part: "content" })).toBe(true);
    expect(ref.current.openNodeDetail("chapter-1", { startParagraph: 1, endParagraph: 1, part: "notes" })).toBe(true);
    expect(ref.current.openNodeDetail("chapter-1", { startParagraph: 2, endParagraph: 2, part: "notes" })).toBe(false);
    expect(alert).toHaveBeenCalledWith("引用段落已不存在，请让 AI 重新生成引用。");
    alert.mockRestore();
  });

  it("resolves markdown references from backend offsets and keeps unmarked links on blank lines", async () => {
    const content = "# 情节一\n\n- 甲\n- 乙";
    const start = content.lastIndexOf("- 乙");
    fetchNodes.mockResolvedValue({
      nodes: [{
        id: "plot-1", type: "plot", title: "情节一", content, extra_data: {},
        position_x: 0, position_y: 0,
      }],
    });
    fetchEdges.mockResolvedValue({ edges: [] });
    const ref = createRef();
    render(<Canvas ref={ref} workId="w-md-ref" />);
    await waitFor(() => expect(ref.current).not.toBeNull());
    const alert = vi.spyOn(window, "alert").mockImplementation(() => {});
    act(() => {
      expect(ref.current.openNodeDetail("plot-1", {
        segmentation: "markdown-v1", start, end: start + "- 乙".length, part: "content",
        startParagraph: 3, endParagraph: 3,
      })).toBe(true);
    });
    expect(ref.current.openNodeDetail("plot-1", {
      segmentation: "markdown-v1", part: "content", startParagraph: 3, endParagraph: 3,
    })).toBe(false);
    expect(ref.current.openNodeDetail("plot-1", { startParagraph: 2, endParagraph: 2, part: "content" })).toBe(true);
    expect(ref.current.openNodeDetail("plot-1", { startParagraph: 3, endParagraph: 3, part: "content" })).toBe(false);
    alert.mockRestore();
  });

  it("carries sort_order from the server into node data", async () => {
    fetchNodes.mockResolvedValue({
      nodes: [
        { id: "n1", type: "chapter", title: "第一章", content: "", extra_data: {}, layer: 3, sort_order: 7, scope: "local", position_x: 0, position_y: 0, locked: false },
      ],
    });
    fetchEdges.mockResolvedValue({ edges: [] });

    render(<Canvas ref={createRef()} workId="w-order" />);
    await waitFor(() => {
      expect(mocks.setNodes).toHaveBeenCalled();
    });
    const loaded = mocks.setNodes.mock.calls[0][0];
    expect(loaded[0].data.sort_order).toBe(7);
  });

  it("renders the workbench explorer instead of the canvas", async () => {
    mocks.nodes = [
      { id: "c1", type: "custom", position: { x: 0, y: 0 }, data: { type: "chapter", label: "第一章", sort_order: 1 } },
      { id: "note", type: "custom", position: { x: 0, y: 0 }, data: { type: "note", label: "写作要求", sort_order: 1, scope: "global" } },
    ];
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });
    render(<Canvas ref={createRef()} workId="w-workbench" />);
    expect(await screen.findByTestId("workbench-explorer")).toBeDefined();
    expect(screen.getByRole("button", { name: "第一章" })).toBeDefined();
    expect(screen.getByRole("button", { name: "写作要求" })).toBeDefined();
    expect(screen.getByText("从左侧选择一项")).toBeDefined();
    expect(screen.queryByTestId("react-flow")).toBeNull();
    expect(screen.queryByRole("button", { name: "定位到首章" })).toBeNull();
  });

  it("selects a chapter from the explorer and can quote or delete it", async () => {
    mocks.nodes = [
      { id: "c1", type: "custom", position: { x: 0, y: 0 }, data: { type: "chapter", label: "第一章", sort_order: 1 } },
    ];
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });
    const onAddContext = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    deleteNode.mockResolvedValue(undefined);
    render(<Canvas ref={createRef()} workId="w-menu" onAddContext={onAddContext} />);
    const row = await screen.findByRole("button", { name: "第一章" });
    fireEvent.click(row);
    fireEvent.contextMenu(row);
    fireEvent.click(screen.getByRole("button", { name: "引用此节点" }));
    expect(onAddContext).toHaveBeenCalledWith(expect.objectContaining({ id: "c1", label: "第一章" }));

    fireEvent.contextMenu(screen.getByRole("button", { name: "第一章" }));
    fireEvent.click(screen.getByRole("button", { name: "删除节点" }));
    expect(confirm).toHaveBeenCalled();
    await waitFor(() => expect(deleteNode).toHaveBeenCalledWith("c1"));
    confirm.mockRestore();
  });

  it("opens the node menu from a long-press in App mode", async () => {
    mocks.nodes = [
      { id: "c1", type: "custom", position: { x: 0, y: 0 }, data: { type: "chapter", label: "第一章", sort_order: 1 } },
    ];
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });
    const onAddContext = vi.fn();
    render(<Canvas ref={createRef()} workId="w-press" appMode onAddContext={onAddContext} />);
    const row = await screen.findByRole("button", { name: "第一章" });
    vi.useFakeTimers();
    try {
      fireEvent.pointerDown(row, { clientX: 20, clientY: 20, button: 0 });
      await act(async () => { await vi.advanceTimersByTimeAsync(500); });
      expect(screen.getByRole("button", { name: "引用此节点" })).toBeDefined();
      fireEvent.pointerUp(row);
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not wire long-press on the web explorer", async () => {
    mocks.nodes = [
      { id: "c1", type: "custom", position: { x: 0, y: 0 }, data: { type: "chapter", label: "第一章", sort_order: 1 } },
    ];
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });
    render(<Canvas ref={createRef()} workId="w-web-press" />);
    const row = await screen.findByRole("button", { name: "第一章" });
    vi.useFakeTimers();
    try {
      fireEvent.pointerDown(row, { clientX: 20, clientY: 20, button: 0 });
      await act(async () => { await vi.advanceTimersByTimeAsync(500); });
      expect(screen.queryByRole("button", { name: "引用此节点" })).toBeNull();
      fireEvent.pointerUp(row);
    } finally {
      vi.useRealTimers();
    }
  });

  it("exposes a refresh method via ref", async () => {
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });

    const ref = createRef();
    render(<Canvas ref={ref} workId="w1" />);

    await waitFor(() => {
      expect(ref.current).not.toBeNull();
    });
    expect(typeof ref.current.refresh).toBe("function");
    expect(typeof ref.current.undo).toBe("function");
  });

  it("refresh() re-fetches nodes and edges from the server", async () => {
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });

    const ref = createRef();
    render(<Canvas ref={ref} workId="w1" />);

    await waitFor(() => {
      expect(fetchNodes).toHaveBeenCalledTimes(1);
    });

    ref.current.refresh();

    await waitFor(() => {
      expect(fetchNodes).toHaveBeenCalledTimes(2);
      expect(fetchEdges).toHaveBeenCalledTimes(2);
    });
  });

  it("refresh() preserves existing node positions and merges new data", async () => {
    fetchNodes.mockResolvedValue({
      nodes: [
        {
          id: "n1",
          type: "idea",
          title: "A",
          content: "initial",
          extra_data: null,
          position_x: 10,
          position_y: 20,
        },
      ],
    });
    fetchEdges.mockResolvedValue({ edges: [] });

    const ref = createRef();
    render(<Canvas ref={ref} workId="w1" />);

    await waitFor(() => {
      expect(fetchNodes).toHaveBeenCalledTimes(1);
    });

    mocks.nodes = [
      {
        id: "n1",
        type: "custom",
        position: { x: 100, y: 200 },
        data: { type: "idea", label: "A", content: "initial", extra_data: null },
      },
    ];
    mocks.setNodes.mockClear();

    fetchNodes.mockResolvedValue({
      nodes: [
        {
          id: "n1",
          type: "idea",
          title: "A",
          content: "updated",
          extra_data: null,
          position_x: 999,
          position_y: 888,
        },
        {
          id: "n2",
          type: "chapter",
          title: "B",
          content: "new node",
          extra_data: null,
          position_x: 50,
          position_y: 60,
        },
      ],
    });

    ref.current.refresh();

    await waitFor(() => {
      expect(mocks.setNodes).toHaveBeenCalled();
    });

    const updateArg = mocks.setNodes.mock.calls[0][0];
    const result = typeof updateArg === "function" ? updateArg(mocks.nodes) : updateArg;

    expect(result).toHaveLength(2);
    const n1 = result.find((n) => n.id === "n1");
    // refresh 时直接用 DB 坐标
    expect(n1.data.content).toBe("updated");
    const n2 = result.find((n) => n.id === "n2");
    expect(n2.position).toEqual({ x: 50, y: 60 });
  });

  it("refresh can be called without errors when workId is absent", async () => {
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });

    const ref = createRef();
    render(<Canvas ref={ref} workId={null} />);

    expect(ref.current).not.toBeNull();
    expect(typeof ref.current.refresh).toBe("function");
  });
});

describe("Canvas undo", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.nodes = [];
    mocks.edges = [];
  });

  it("restores the previous server snapshot after a refreshed agent change", async () => {
    fetchNodes
      .mockResolvedValueOnce({
        nodes: [{
          id: "n1", type: "idea", title: "旧", content: "",
          extra_data: {}, layer: 0, position_x: 1, position_y: 2,
        }],
      })
      .mockResolvedValueOnce({
        nodes: [{
          id: "n1", type: "idea", title: "新", content: "",
          extra_data: {}, layer: 0, position_x: 1, position_y: 2,
        }],
      });
    fetchEdges.mockResolvedValue({ edges: [] });
    restoreCanvasSnapshot.mockResolvedValue({ success: true });

    const ref = createRef();
    render(<Canvas ref={ref} workId="w1" />);
    await waitFor(() => expect(fetchNodes).toHaveBeenCalledTimes(1));

    mocks.nodes = [{
      id: "n1",
      type: "custom",
      position: { x: 1, y: 2 },
      data: { type: "idea", label: "旧", content: "", extra_data: {}, layer: 0 },
    }];
    await ref.current.refresh();
    await ref.current.undo();

    expect(restoreCanvasSnapshot).toHaveBeenCalledWith(
      "w1",
      expect.objectContaining({
        nodes: [expect.objectContaining({ id: "n1", title: "旧" })],
      })
    );
  });
});

// ── Canvas 删除节点测试 ──

describe("Canvas deleteNode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.nodes = [];
    mocks.edges = [];
  });

  it("handleDeleteNode calls deleteNode API and removes the node from state", async () => {
    const initialNodes = [
      { id: "n1", type: "custom", position: { x: 10, y: 20 }, data: { type: "idea", label: "A", content: "" } },
      { id: "n2", type: "custom", position: { x: 30, y: 40 }, data: { type: "idea", label: "B", content: "" } },
    ];
    const initialEdges = [
      { id: "e1", source: "n1", target: "n2", type: "smoothstep", style: {}, markerEnd: {}, data: { edge_type: "contains" } },
    ];

    mocks.nodes = initialNodes;
    mocks.edges = initialEdges;

    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });
    deleteNode.mockResolvedValue(undefined);

    const ref = createRef();
    render(<Canvas ref={ref} workId="w1" />);

    await waitFor(() => {
      expect(fetchNodes).toHaveBeenCalledTimes(1);
    });

    mocks.setNodes.mockClear();
    mocks.setEdges.mockClear();

    const nodeToDelete = { id: "n1", type: "idea", label: "A", content: "" };
    await ref.current.handleDeleteNode(nodeToDelete);

    expect(deleteNode).toHaveBeenCalledWith("n1");

    const nodesUpdater = mocks.setNodes.mock.calls[0][0];
    const updatedNodes = nodesUpdater(initialNodes);
    expect(updatedNodes).toHaveLength(1);
    expect(updatedNodes.find((n) => n.id === "n1")).toBeUndefined();

    const edgesUpdater = mocks.setEdges.mock.calls[0][0];
    const updatedEdges = edgesUpdater(initialEdges);
    expect(updatedEdges).toHaveLength(0);
  });

  it("deletes selected nodes when Delete key is pressed", async () => {
    const initialNodes = [
      { id: "n1", type: "custom", selected: true, position: { x: 10, y: 20 }, data: { type: "chapter", label: "A", content: "" } },
      { id: "n2", type: "custom", selected: true, position: { x: 30, y: 40 }, data: { type: "chapter", label: "B", content: "" } },
      { id: "n3", type: "custom", selected: false, position: { x: 50, y: 60 }, data: { type: "chapter", label: "C", content: "" } },
    ];
    const initialEdges = [
      { id: "e1", source: "n1", target: "n2", type: "smoothstep", style: {}, markerEnd: {}, data: { edge_type: "contains" } },
      { id: "e2", source: "n2", target: "n3", type: "smoothstep", style: {}, markerEnd: {}, data: { edge_type: "contains" } },
    ];
    mocks.nodes = initialNodes;
    mocks.edges = initialEdges;
    deleteNode.mockResolvedValue(undefined);

    render(<Canvas ref={createRef()} workId="w1" />);

    await waitFor(() => {
      expect(fetchNodes).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(await screen.findByTestId("explorer-item-n1"));
    fireEvent.click(screen.getByTestId("explorer-item-n2"), { ctrlKey: true });

    mocks.setNodes.mockClear();
    mocks.setEdges.mockClear();
    deleteNode.mockClear();

    fireEvent.keyDown(window, { key: "Delete" });

    await waitFor(() => {
      expect(deleteNode).toHaveBeenCalledTimes(2);
    });
    expect(deleteNode).toHaveBeenCalledWith("n1");
    expect(deleteNode).toHaveBeenCalledWith("n2");

    const nodesUpdater = mocks.setNodes.mock.calls[0][0];
    expect(nodesUpdater(initialNodes).map((n) => n.id)).toEqual(["n3"]);

    const edgesUpdater = mocks.setEdges.mock.calls[0][0];
    expect(edgesUpdater(initialEdges).map((e) => e.id)).toEqual([]);
  });

  it("deletes selected nodes when Backspace key is pressed", async () => {
    mocks.nodes = [
      { id: "n1", type: "custom", position: { x: 0, y: 0 }, data: { type: "chapter", label: "A", content: "" } },
    ];
    deleteNode.mockResolvedValue(undefined);

    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => expect(fetchNodes).toHaveBeenCalledTimes(1));

    fireEvent.click(await screen.findByTestId("explorer-item-n1"));
    deleteNode.mockClear();

    fireEvent.keyDown(window, { key: "Backspace" });

    await waitFor(() => expect(deleteNode).toHaveBeenCalledWith("n1"));
  });

  it("does not delete nodes when focus is in an input", async () => {
    mocks.nodes = [
      { id: "n1", type: "custom", selected: true, position: { x: 0, y: 0 }, data: { type: "chapter", label: "A", content: "" } },
    ];
    deleteNode.mockResolvedValue(undefined);

    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => expect(fetchNodes).toHaveBeenCalledTimes(1));

    deleteNode.mockClear();
    const input = document.createElement("input");
    document.body.appendChild(input);
    fireEvent.keyDown(input, { key: "Delete" });
    document.body.removeChild(input);

    expect(deleteNode).not.toHaveBeenCalled();
  });
});

// ── 可见子图与动态布局接入 ──

describe("Canvas 独立章节接入", () => {
  const flowNode = (id, type, order, label) => ({ id, type: "custom", position: { x: 9999, y: 9999 },
    data: { type, label: label || id, sort_order: order, scope: type === "chapter" ? "local" : "global", content: "", extra_data: {} } });
  beforeEach(() => {
    cleanup();
    vi.clearAllMocks();
    mocks.lastReactFlowProps = null;
    mocks.nodes = [flowNode("c2", "chapter", 2, "第二章"), flowNode("c1", "chapter", 1, "第一章"), flowNode("note", "note", 1, "写作要求")];
    mocks.edges = [];
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });
  });
  it("全部章节和资料显示在左侧列表", async () => {
    render(<Canvas ref={createRef()} workId="flat" />);
    expect(await screen.findByRole("button", { name: "第一章" })).toBeDefined();
    expect(screen.getByRole("button", { name: "第二章" })).toBeDefined();
    expect(screen.getByRole("button", { name: "写作要求" })).toBeDefined();
    const chapterButtons = ["第一章", "第二章"].map((name) => screen.getByRole("button", { name }));
    expect(chapterButtons[0].compareDocumentPosition(chapterButtons[1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByTestId("react-flow")).toBeNull();
  });
  it("新增入口只提供五类节点", async () => {
    render(<Canvas ref={createRef()} workId="flat" />);
    await screen.findByRole("button", { name: "添加章节" });
    for (const label of ["大纲", "卷", "情节"]) expect(screen.queryByRole("button", { name: `添加${label}` })).toBeNull();
    for (const label of ["章节", "角色", "世界观", "笔记", "评审笔记"]) {
      expect(screen.getByRole("button", { name: `添加${label}` })).toBeDefined();
    }
  });
});

describe("Canvas 不再回写布局数据", () => {
  const flowNode = (id, type, label) => ({
    id,
    type: "custom",
    position: { x: 100, y: 100 },
    data: { type, label, scope: "local", content: "", extra_data: {}, layer: 0 },
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.lastReactFlowProps = null;
    mocks.nodes = [
      flowNode("o1", "outline", "大纲"),
      flowNode("v1", "volume", "第一卷"),
    ];
    mocks.edges = [
      {
        id: "o1->v1",
        source: "o1",
        target: "v1",
        data: { edge_type: "包含", extra_data: {} },
      },
    ];
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });
  });

  it("展开状态变化不会触发连线数据写入", async () => {
    vi.useFakeTimers();
    try {
      render(<Canvas ref={createRef()} workId="w1" />);
      await vi.advanceTimersByTimeAsync(2000);
      expect(updateNode).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("跨作品复制节点", () => {
  const works = [
    { id: "w-current", title: "当前小说" },
    { id: "w-other", title: "另一部小说" },
  ];
  const chapter = {
    id: "vol",
    data: { type: "chapter", label: "第一章", sort_order: 1, extra_data: { characters: [{ id: "hero", name: "林舟" }] } },
  };

  beforeEach(() => {
    cleanup();
    vi.clearAllMocks();
    mocks.nodes = [
      chapter,
      { id: "plot", data: { type: "plot", label: "开端", sort_order: 1, extra_data: {} } },
      {
        id: "ch",
        data: {
          type: "chapter",
          label: "第一章",
          sort_order: 1,
          extra_data: { characters: [{ id: "hero", name: "林舟" }] },
        },
      },
      { id: "hero", data: { type: "character", label: "林舟", sort_order: 1, scope: "global", extra_data: {} } },
      { id: "note", data: { type: "note", label: "写作要求", sort_order: 1, scope: "global", extra_data: {} } },
      { id: "world", data: { type: "worldbuilding", label: "灵气体系", sort_order: 1, scope: "global", extra_data: {} } },
    ];
    mocks.edges = [
      { id: "vol-plot", source: "vol", target: "plot" },
      { id: "plot-ch", source: "plot", target: "ch" },
    ];
    mocks.lastReactFlowProps = null;
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });
    copyNodeToWork.mockReset();
  });

  function renderCanvas(extraProps = {}) {
    render(
      <Canvas
        ref={createRef()}
        workId="w-current"
        works={works}
        {...extraProps}
      />,
    );
  }

  function openChapterMenu() {
    fireEvent.contextMenu(screen.getByTestId("explorer-item-vol"));
  }

  it("copies a node and its descendants into another work", async () => {
    copyNodeToWork.mockResolvedValue({ nodes: [], edges: [], omitted_character_refs: ["ghost"] });
    renderCanvas();
    await screen.findByTestId("explorer-item-vol");
    openChapterMenu();

    fireEvent.click(screen.getByRole("button", { name: "复制到其他作品" }));

    expect(screen.getByRole("dialog", { name: "复制到其他作品" }).textContent).toContain(
      "「第一章」会连同章节引用的 1 个角色，一起复制到所选作品，并作为独立结构放在那里。",
    );
    expect(screen.queryByRole("button", { name: "当前小说" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "另一部小说" }));

    await waitFor(() => expect(copyNodeToWork).toHaveBeenCalledWith("vol", "w-other"));
    expect(screen.getByText("已复制到「另一部小说」。有 1 条已失效的角色引用未复制。")).toBeDefined();
  });

  it("shows the request error and keeps the dialog open", async () => {
    copyNodeToWork.mockRejectedValue(new Error("不能复制到当前作品"));
    renderCanvas();
    await screen.findByTestId("explorer-item-vol");
    openChapterMenu();
    fireEvent.click(screen.getByRole("button", { name: "复制到其他作品" }));
    fireEvent.click(screen.getByRole("button", { name: "另一部小说" }));

    expect(await screen.findByText("不能复制到当前作品")).toBeDefined();
    expect(screen.getByRole("dialog", { name: "复制到其他作品" })).toBeDefined();
  });

  it("explains when the account has no other work", async () => {
    renderCanvas({ workId: "w-only", works: [{ id: "w-only", title: "只有这部" }] });
    await screen.findByTestId("explorer-item-vol");
    openChapterMenu();
    fireEvent.click(screen.getByRole("button", { name: "复制到其他作品" }));

    expect(screen.getByText("还没有其他作品。先在左上角创建一部作品，再把节点复制过去。")).toBeDefined();
  });

  it("copies a side-panel character by itself", async () => {
    copyNodeToWork.mockResolvedValue({ nodes: [], edges: [], omitted_character_refs: [] });
    renderCanvas();
    await screen.findByTestId("workbench-explorer");

    fireEvent.contextMenu(screen.getByRole("button", { name: "林舟" }));
    fireEvent.click(screen.getByRole("button", { name: "复制到其他作品" }));

    expect(screen.getByRole("dialog", { name: "复制到其他作品" }).textContent).toContain(
      "「林舟」会复制到所选作品，并作为独立结构放在那里。",
    );
    fireEvent.click(screen.getByRole("button", { name: "另一部小说" }));
    await waitFor(() => expect(copyNodeToWork).toHaveBeenCalledWith("hero", "w-other"));
    expect(screen.getByText("已复制到「另一部小说」。")).toBeDefined();
  });

  it.each([
    ["写作要求", "note", "「写作要求」会复制到所选作品，并作为独立结构放在那里。"],
    ["灵气体系", "world", "「灵气体系」会复制到所选作品，并作为独立结构放在那里。"],
  ])("右键「%s」后复制到其他作品", async (label, nodeId, description) => {
    copyNodeToWork.mockResolvedValue({ nodes: [], edges: [], omitted_character_refs: [] });
    renderCanvas();
    await screen.findByTestId("workbench-explorer");

    fireEvent.contextMenu(screen.getByRole("button", { name: label }));
    fireEvent.click(screen.getByRole("button", { name: "复制到其他作品" }));

    expect(screen.getByRole("dialog", { name: "复制到其他作品" }).textContent).toContain(description);
    fireEvent.click(screen.getByRole("button", { name: "另一部小说" }));
    await waitFor(() => expect(copyNodeToWork).toHaveBeenCalledWith(nodeId, "w-other"));
  });
});
