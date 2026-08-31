import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { createRef } from "react";

const mocks = vi.hoisted(() => ({
  nodes: [],
  setNodes: vi.fn(),
  edges: [],
  setEdges: vi.fn(),
  relationEdges: [],
  setRelationEdges: vi.fn(),
  edgesStateCall: 0,
  lastReactFlowProps: null,
  customNodeProps: [],
}));

vi.mock("@xyflow/react", async () => {
  const React = await import("react");
  return {
    ReactFlow: (props) => {
      mocks.lastReactFlowProps = props;
      return React.createElement("div", { "data-testid": "react-flow" }, props.children);
    },
    ReactFlowProvider: ({ children }) => children,
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    addEdge: (edge, edges) => [...edges, edge],
    useNodesState: () => [mocks.nodes, mocks.setNodes, vi.fn()],
    useEdgesState: () => {
      mocks.edgesStateCall += 1;
      if (mocks.edgesStateCall % 2 === 1) {
        return [mocks.edges, mocks.setEdges, vi.fn()];
      }
      return [mocks.relationEdges, mocks.setRelationEdges, vi.fn()];
    },
    MarkerType: { ArrowClosed: "arrowclosed" },
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
  fetchCharacterRelations: vi.fn(),
  createNode: vi.fn(),
  updateNode: vi.fn(),
  createEdge: vi.fn(),
  updateEdge: vi.fn(),
  deleteEdge: vi.fn(),
  deleteNode: vi.fn(),
  restoreCanvasSnapshot: vi.fn(),
  createCharacterRelation: vi.fn(),
  deleteCharacterRelation: vi.fn(),
}));

import { Canvas, mergeRefreshedNodes, toCanvasSnapshot, applyNodeUpdateToData } from "./Canvas";
import {
  fetchNodes,
  fetchEdges,
  fetchCharacterRelations,
  deleteNode,
  restoreCanvasSnapshot,
  updateEdge,
  updateNode,
} from "../lib/canvasApi";
import { CANVAS_MARQUEE_KEY_CODE } from "../lib/canvasDrag";
import { loadViewState, saveViewState } from "../lib/canvasViewState";

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
          extra_data: { a: 1 },
          layer: 2,
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
        extra_data: { a: 1 },
        layer: 2,
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
      character_relations: [],
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
    expect(snap.character_relations).toEqual([]);
  });

  it("serializes character relations", () => {
    const snap = toCanvasSnapshot([], [], [{
      id: "r1",
      source: "c1",
      target: "c2",
      data: { relation_type: "暗恋", label: "秘密" },
    }]);
    expect(snap.character_relations).toEqual([{
      id: "r1",
      source_id: "c1",
      target_id: "c2",
      relation_type: "暗恋",
      label: "秘密",
    }]);
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

  it("merges chapter_elements into extra_data preserving other fields", () => {
    const prev = {
      label: "x",
      content: "",
      extra_data: { last_generation: { ok: true }, chapter_elements: [{ id: "old" }] },
    };
    const next = applyNodeUpdateToData(prev, { chapter_elements: [{ id: "new" }] });
    expect(next.extra_data.chapter_elements).toEqual([{ id: "new" }]);
    expect(next.extra_data.last_generation).toEqual({ ok: true });
  });

  it("preserves label/content when title/content absent in update", () => {
    const prev = { label: "保留", content: "保留c", extra_data: {} };
    const next = applyNodeUpdateToData(prev, { chapter_elements: [] });
    expect(next.label).toBe("保留");
    expect(next.content).toBe("保留c");
    expect(next.extra_data.chapter_elements).toEqual([]);
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
    mocks.relationEdges = [];
    mocks.edgesStateCall = 0;
    mocks.lastReactFlowProps = null;
    fetchCharacterRelations.mockResolvedValue({ relations: [], total: 0 });
  });

  it("enables Ctrl+drag marquee selection on ReactFlow", async () => {
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });

    render(<Canvas ref={createRef()} workId="w1" />);

    await waitFor(() => {
      expect(mocks.lastReactFlowProps).not.toBeNull();
    });
    expect(mocks.lastReactFlowProps.selectionKeyCode).toBe(CANVAS_MARQUEE_KEY_CODE);
    expect(mocks.lastReactFlowProps.multiSelectionKeyCode).toBe(CANVAS_MARQUEE_KEY_CODE);
    expect(typeof mocks.lastReactFlowProps.onSelectionDragStop).toBe("function");
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
      expect(fetchCharacterRelations).toHaveBeenCalledTimes(2);
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
    const initialRelations = [
      { id: "r1", source: "n1", target: "n2", type: "characterRelation", data: { relation_type: "ally" } },
    ];

    mocks.nodes = initialNodes;
    mocks.edges = initialEdges;
    mocks.relationEdges = initialRelations;
    deleteNode.mockResolvedValue(undefined);

    render(<Canvas ref={createRef()} workId="w1" />);

    await waitFor(() => {
      expect(fetchNodes).toHaveBeenCalledTimes(1);
    });

    mocks.lastReactFlowProps.onSelectionChange({
      nodes: [{ id: "n1" }, { id: "n2" }],
    });

    mocks.setNodes.mockClear();
    mocks.setEdges.mockClear();
    mocks.setRelationEdges.mockClear();
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

    const relationsUpdater = mocks.setRelationEdges.mock.calls[0][0];
    expect(relationsUpdater(initialRelations)).toEqual([]);
  });

  it("deletes selected nodes when Backspace key is pressed", async () => {
    mocks.nodes = [
      { id: "n1", type: "custom", position: { x: 0, y: 0 }, data: { type: "chapter", label: "A", content: "" } },
    ];
    deleteNode.mockResolvedValue(undefined);

    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => expect(fetchNodes).toHaveBeenCalledTimes(1));

    mocks.lastReactFlowProps.onSelectionChange({ nodes: [{ id: "n1" }] });
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

describe("Canvas 可见子图接入", () => {
  const flowNode = (id, type, label, scope = "local") => ({
    id,
    type: "custom",
    position: { x: 9999, y: 9999 },
    data: { type, label, scope, content: "", extra_data: {}, layer: 0 },
  });

  const flowEdge = (source, target, edgeType = "包含") => ({
    id: `${source}->${target}`,
    source,
    target,
    data: { edge_type: edgeType, extra_data: {} },
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.edgesStateCall = 0;
    mocks.lastReactFlowProps = null;
    mocks.relationEdges = [];
    fetchNodes.mockResolvedValue({ nodes: [] });
    fetchEdges.mockResolvedValue({ edges: [] });
    fetchCharacterRelations.mockResolvedValue({ relations: [], total: 0 });

    mocks.nodes = [
      flowNode("o1", "outline", "大纲"),
      flowNode("v1", "volume", "第一卷"),
      flowNode("v2", "volume", "第二卷"),
      flowNode("p1", "plot", "情节一"),
      flowNode("c1", "chapter", "第1章"),
      flowNode("w1", "worldbuilding", "世界观", "global"),
      flowNode("n1", "note", "笔记", "global"),
      flowNode("hero", "character", "主角", "global"),
    ];
    mocks.edges = [
      flowEdge("o1", "v1"),
      flowEdge("o1", "v2"),
      flowEdge("v1", "p1"),
      flowEdge("p1", "c1"),
    ];
  });

  const renderCanvas = async () => {
    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => {
      expect(mocks.lastReactFlowProps).not.toBeNull();
    });
    return mocks.lastReactFlowProps;
  };

  it("默认只把主干节点交给 ReactFlow 渲染", async () => {
    const props = await renderCanvas();
    const ids = props.nodes.map((n) => n.id);
    expect(new Set(ids)).toEqual(new Set(["o1", "v1", "v2"]));
  });

  it("更深层节点默认不渲染", async () => {
    const props = await renderCanvas();
    const ids = props.nodes.map((n) => n.id);
    expect(ids).not.toContain("p1");
    expect(ids).not.toContain("c1");
  });

  it("孤立节点不占用画布", async () => {
    const props = await renderCanvas();
    const ids = props.nodes.map((n) => n.id);
    expect(ids).not.toContain("w1");
    expect(ids).not.toContain("n1");
    expect(ids).not.toContain("hero");
  });

  it("隐藏节点仍保留在完整数据中", async () => {
    await renderCanvas();
    // mocks.nodes 是完整语义图，投影不会从中删除节点
    expect(mocks.nodes.map((n) => n.id)).toContain("c1");
    expect(mocks.nodes.map((n) => n.id)).toContain("w1");
  });

  it("节点坐标由布局计算，不使用数据库坐标", async () => {
    const props = await renderCanvas();
    for (const node of props.nodes) {
      expect(node.position.x).not.toBe(9999);
      expect(node.position.y).not.toBe(9999);
    }
  });

  it("层级链节点不可手动拖动", async () => {
    const props = await renderCanvas();
    for (const node of props.nodes) {
      expect(node.draggable).toBe(false);
    }
  });

  it("只保留两端都可见的结构连线", async () => {
    const props = await renderCanvas();
    const ids = props.edges.map((e) => e.id);
    expect(new Set(ids)).toEqual(new Set(["o1->v1", "o1->v2"]));
  });

  it("父节点位于可见子节点的水平中心", async () => {
    const props = await renderCanvas();
    const byId = new Map(props.nodes.map((n) => [n.id, n.position]));
    const parentCenter = byId.get("o1").x;
    const childrenCenter = (byId.get("v1").x + byId.get("v2").x) / 2;
    expect(parentCenter).toBeCloseTo(childrenCenter, 5);
  });

  it("同一层级的节点纵坐标一致且低于父层", async () => {
    const props = await renderCanvas();
    const byId = new Map(props.nodes.map((n) => [n.id, n.position]));
    expect(byId.get("v1").y).toBe(byId.get("v2").y);
    expect(byId.get("v1").y).toBeGreaterThan(byId.get("o1").y);
  });

  it("为有隐藏后代的节点提供展开控件与摘要", async () => {
    const props = await renderCanvas();
    expect(typeof props.nodeTypes.custom).toBe("function");
  });

  it("空图不报错", async () => {
    mocks.nodes = [];
    mocks.edges = [];
    const props = await renderCanvas();
    expect(props.nodes).toEqual([]);
    expect(props.edges).toEqual([]);
  });
});

// ── 布局接管后的职责清理 ──

describe("Canvas 不再回写布局数据", () => {
  const flowNode = (id, type, label) => ({
    id,
    type: "custom",
    position: { x: 100, y: 100 },
    data: { type, label, scope: "local", content: "", extra_data: {}, layer: 0 },
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.edgesStateCall = 0;
    mocks.lastReactFlowProps = null;
    mocks.relationEdges = [];
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
    fetchCharacterRelations.mockResolvedValue({ relations: [], total: 0 });
  });

  it("不再把连线布局诊断写回后端", async () => {
    vi.useFakeTimers();
    try {
      render(<Canvas ref={createRef()} workId="w1" />);
      await vi.advanceTimersByTimeAsync(2000);
      expect(updateEdge).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("展开状态变化不会触发连线数据写入", async () => {
    vi.useFakeTimers();
    try {
      render(<Canvas ref={createRef()} workId="w1" />);
      await vi.advanceTimersByTimeAsync(2000);
      // 布局现在每次展开都会变化，若仍回写诊断会产生大量无意义请求
      expect(updateEdge).not.toHaveBeenCalled();
      expect(updateNode).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("画布视图状态持久化", () => {
  const flowNode = (id, type, label) => ({
    id,
    type: "custom",
    position: { x: 0, y: 0 },
    data: { type, label, scope: "local", content: "", extra_data: {}, layer: 0 },
  });
  const hierEdge = (source, target) => ({
    id: `${source}->${target}`,
    source,
    target,
    data: { edge_type: "包含", extra_data: {} },
  });

  const visibleIds = () =>
    (mocks.lastReactFlowProps?.nodes || []).map((n) => n.id);

  beforeEach(() => {
    // 上个用例的画布若不卸载，其 effect 会继续写入同一份视图记录
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
    mocks.edgesStateCall = 0;
    mocks.lastReactFlowProps = null;
    mocks.customNodeProps = [];
    mocks.relationEdges = [];
    mocks.nodes = [
      flowNode("o1", "outline", "大纲"),
      flowNode("v1", "volume", "第一卷"),
      flowNode("p1", "plot", "开篇情节"),
    ];
    mocks.edges = [hierEdge("o1", "v1"), hierEdge("v1", "p1")];
    fetchNodes.mockResolvedValue({
      nodes: mocks.nodes.map((node) => ({
        id: node.id,
        type: node.data.type,
        title: node.data.label,
        content: "",
        position_x: 0,
        position_y: 0,
        extra_data: {},
        layer: 0,
        scope: "local",
      })),
    });
    fetchEdges.mockResolvedValue({ edges: [] });
    fetchCharacterRelations.mockResolvedValue({ relations: [], total: 0 });
  });

  it("无记录时按默认深度显示，不展示更深层级", async () => {
    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => {
      expect(mocks.lastReactFlowProps).not.toBeNull();
    });
    expect(visibleIds()).toEqual(["o1", "v1"]);
  });

  it("恢复已保存的展开状态", async () => {
    saveViewState(
      "w1",
      { expandedNodeIds: new Set(["v1"]), viewport: null },
      window.localStorage,
    );

    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => {
      expect(visibleIds()).toContain("p1");
    });
  });

  it("其他作品的记录不会影响当前作品", async () => {
    saveViewState(
      "other",
      { expandedNodeIds: new Set(["v1"]), viewport: null },
      window.localStorage,
    );

    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => {
      expect(mocks.lastReactFlowProps).not.toBeNull();
    });
    expect(visibleIds()).not.toContain("p1");
  });

  it("展开节点后写入本地记录", async () => {
    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => {
      expect(mocks.lastReactFlowProps).not.toBeNull();
    });

    const NodeComp = mocks.lastReactFlowProps.nodeTypes.custom;
    mocks.customNodeProps = [];
    render(<NodeComp id="v1" data={mocks.nodes[1].data} />);

    const props = mocks.customNodeProps.at(-1);
    await act(async () => {
      props.onCollapseToggle("v1");
    });

    await waitFor(() => {
      const saved = loadViewState("w1", window.localStorage);
      expect(saved?.expandedNodeIds.has("v1")).toBe(true);
    });
  });

  it("保存时剔除已不存在的节点", async () => {
    saveViewState(
      "w1",
      { expandedNodeIds: new Set(["v1", "deleted-node"]), viewport: null },
      window.localStorage,
    );

    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => {
      const saved = loadViewState("w1", window.localStorage);
      expect(saved?.expandedNodeIds.has("deleted-node")).toBe(false);
    });
    expect(loadViewState("w1", window.localStorage).expandedNodeIds.has("v1")).toBe(true);
  });

  it("存在已保存 viewport 时恢复它并跳过自动适配", async () => {
    saveViewState(
      "w1",
      { expandedNodeIds: new Set(), viewport: { x: 40, y: -20, zoom: 0.6 } },
      window.localStorage,
    );

    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => {
      expect(mocks.lastReactFlowProps).not.toBeNull();
    });

    expect(mocks.lastReactFlowProps.defaultViewport).toEqual({
      x: 40,
      y: -20,
      zoom: 0.6,
    });
    expect(mocks.lastReactFlowProps.fitView).toBe(false);
  });

  it("无 viewport 记录时保留自动适配", async () => {
    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => {
      expect(mocks.lastReactFlowProps).not.toBeNull();
    });
    expect(mocks.lastReactFlowProps.fitView).toBe(true);
  });

  it("切换作品时改用新作品的展开状态", async () => {
    saveViewState(
      "w2",
      { expandedNodeIds: new Set(["v1"]), viewport: null },
      window.localStorage,
    );

    const { rerender } = render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => {
      expect(mocks.lastReactFlowProps).not.toBeNull();
    });
    expect(visibleIds()).not.toContain("p1");

    rerender(<Canvas ref={createRef()} workId="w2" />);
    await waitFor(() => {
      expect(visibleIds()).toContain("p1");
    });
  });

  it("画布平移后记录 viewport", async () => {
    render(<Canvas ref={createRef()} workId="w1" />);
    await waitFor(() => {
      expect(mocks.lastReactFlowProps).not.toBeNull();
    });

    await act(async () => {
      mocks.lastReactFlowProps.onMoveEnd(null, { x: 5, y: 6, zoom: 1.5 });
    });

    await waitFor(() => {
      expect(loadViewState("w1", window.localStorage)?.viewport).toEqual({
        x: 5,
        y: 6,
        zoom: 1.5,
      });
    });
  });
});
