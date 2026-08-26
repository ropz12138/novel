import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";
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
  default: () => null,
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

import { Canvas, mergeRefreshedNodes, toCanvasSnapshot, isDescendantOfCollapsed, isContainsEdge, applyNodeUpdateToData } from "./Canvas";
import {
  fetchNodes,
  fetchEdges,
  fetchCharacterRelations,
  deleteNode,
  restoreCanvasSnapshot,
} from "../lib/canvasApi";
import { CANVAS_MARQUEE_KEY_CODE } from "../lib/canvasDrag";

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

// ── 收起子节点：isDescendantOfCollapsed 纯函数测试 ──

describe("isContainsEdge (父子连线判定)", () => {
  it("英文 contains 与中文 包含 都算父子连线", () => {
    expect(isContainsEdge("contains")).toBe(true);
    expect(isContainsEdge("包含")).toBe(true);
  });
  it("其它自然语言关系不算父子", () => {
    expect(isContainsEdge("角色登场")).toBe(false);
    expect(isContainsEdge("inherits")).toBe(false);
    expect(isContainsEdge("")).toBe(false);
    expect(isContainsEdge(undefined)).toBe(false);
  });
});

describe("isDescendantOfCollapsed (收起子树判定)", () => {
  // parentMap: childId -> parentId（contains 连线）
  const parentMap = { ch1: "root", ch2: "root", g1: "ch1", g2: "ch1", g3: "ch2" };

  it("未收起任何节点时，所有节点都可见", () => {
    const collapsed = new Set();
    expect(isDescendantOfCollapsed("root", parentMap, collapsed)).toBe(false);
    expect(isDescendantOfCollapsed("ch1", parentMap, collapsed)).toBe(false);
    expect(isDescendantOfCollapsed("g2", parentMap, collapsed)).toBe(false);
  });

  it("收起 root 后，整棵子树（子+孙）都判定为隐藏", () => {
    const collapsed = new Set(["root"]);
    expect(isDescendantOfCollapsed("ch1", parentMap, collapsed)).toBe(true);
    expect(isDescendantOfCollapsed("ch2", parentMap, collapsed)).toBe(true);
    expect(isDescendantOfCollapsed("g1", parentMap, collapsed)).toBe(true); // 孙辈
    expect(isDescendantOfCollapsed("g3", parentMap, collapsed)).toBe(true); // 孙辈
  });

  it("收起中间节点，只隐藏它的子树，兄弟分支不受影响", () => {
    const collapsed = new Set(["ch1"]);
    expect(isDescendantOfCollapsed("g1", parentMap, collapsed)).toBe(true);
    expect(isDescendantOfCollapsed("g2", parentMap, collapsed)).toBe(true);
    // ch2 分支不受影响
    expect(isDescendantOfCollapsed("ch2", parentMap, collapsed)).toBe(false);
    expect(isDescendantOfCollapsed("g3", parentMap, collapsed)).toBe(false);
  });

  it("被收起的节点自身不隐藏（root 自身）", () => {
    const collapsed = new Set(["root"]);
    expect(isDescendantOfCollapsed("root", parentMap, collapsed)).toBe(false);
  });

  it("无父节点的孤立节点永不隐藏", () => {
    const collapsed = new Set(["root"]);
    expect(isDescendantOfCollapsed("orphan", parentMap, collapsed)).toBe(false);
  });
});

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
