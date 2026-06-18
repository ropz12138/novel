import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { createRef } from "react";

const mocks = vi.hoisted(() => ({
  nodes: [],
  setNodes: vi.fn(),
  edges: [],
  setEdges: vi.fn(),
}));

vi.mock("@xyflow/react", async () => {
  const React = await import("react");
  return {
    ReactFlow: (props) =>
      React.createElement("div", { "data-testid": "react-flow" }, props.children),
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    addEdge: (edge, edges) => [...edges, edge],
    useNodesState: () => [mocks.nodes, mocks.setNodes, vi.fn()],
    useEdgesState: () => [mocks.edges, mocks.setEdges, vi.fn()],
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
  createNode: vi.fn(),
  updateNode: vi.fn(),
  createEdge: vi.fn(),
  deleteEdge: vi.fn(),
  deleteNode: vi.fn(),
}));

import { Canvas, mergeRefreshedNodes, autoLayout } from "./Canvas";
import { fetchNodes, fetchEdges, deleteNode } from "../lib/canvasApi";

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
    expect(result[0].position).toEqual({ x: 100, y: 200 });
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
    expect(result[0].position).toEqual({ x: 100, y: 200 });
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
    expect(n1.position).toEqual({ x: 10, y: 20 });
    expect(n1.data.content).toBe("new");
    const n3 = result.find((n) => n.id === "n3");
    expect(n3.position).toEqual({ x: 50, y: 60 });
    expect(result.find((n) => n.id === "n2")).toBeUndefined();
  });
});

// ── Canvas 组件集成测试 ──

describe("Canvas forwardRef", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.nodes = [];
    mocks.edges = [];
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

    const updaterFn = mocks.setNodes.mock.calls[0][0];
    const result = updaterFn(mocks.nodes);

    expect(result).toHaveLength(2);
    const n1 = result.find((n) => n.id === "n1");
    expect(n1.position).toEqual({ x: 100, y: 200 });
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
});

// ── autoLayout (layer 驱动) 测试 ──

describe("autoLayout (layer-driven)", () => {
  it("groups nodes by layer into rows", () => {
    const nodes = [
      { id: "n1", data: { layer: 0 }, position: { x: 0, y: 0 } },
      { id: "n2", data: { layer: 1 }, position: { x: 0, y: 0 } },
      { id: "n3", data: { layer: 0 }, position: { x: 0, y: 0 } },
    ];
    const result = autoLayout(nodes, []);
    const n1 = result.find((n) => n.id === "n1");
    const n3 = result.find((n) => n.id === "n3");
    const n2 = result.find((n) => n.id === "n2");
    expect(n1.position.y).toBe(n3.position.y);
    expect(n2.position.y).toBeGreaterThan(n1.position.y);
  });

  it("places same-layer nodes in a horizontal row with distinct x", () => {
    const nodes = [
      { id: "a", data: { layer: 0 }, position: { x: 0, y: 0 } },
      { id: "b", data: { layer: 0 }, position: { x: 0, y: 0 } },
    ];
    const result = autoLayout(nodes, []);
    expect(result[0].position.y).toBe(result[1].position.y);
    expect(result[0].position.x).not.toBe(result[1].position.x);
  });

  it("defaults layer to 0 when missing", () => {
    const nodes = [{ id: "n1", data: {}, position: { x: 5, y: 5 } }];
    const result = autoLayout(nodes, []);
    expect(result[0].position.y).toBe(0);
  });

  it("does not depend on edges (natural-language relations ignored)", () => {
    const nodes = [
      { id: "n1", data: { layer: 0 }, position: { x: 0, y: 0 } },
      { id: "n2", data: { layer: 1 }, position: { x: 0, y: 0 } },
    ];
    const edges = [
      { source: "n1", target: "n2", data: { edge_type: "contains" } },
    ];
    const result = autoLayout(nodes, edges);
    const n1 = result.find((n) => n.id === "n1");
    const n2 = result.find((n) => n.id === "n2");
    expect(n1.position.y).toBeLessThan(n2.position.y);
  });

  it("skips manually positioned nodes", () => {
    const nodes = [
      { id: "n1", data: { layer: 0, manuallyPositioned: true }, position: { x: 999, y: 999 } },
      { id: "n2", data: { layer: 0 }, position: { x: 0, y: 0 } },
    ];
    const result = autoLayout(nodes, []);
    const n1 = result.find((n) => n.id === "n1");
    expect(n1.position).toEqual({ x: 999, y: 999 });
  });

  it("returns empty for empty input", () => {
    expect(autoLayout([], [])).toEqual([]);
  });

  it("places character nodes vertically on the left", () => {
    const nodes = [
      { id: "c1", data: { type: "character", layer: 0 }, position: { x: 0, y: 0 } },
      { id: "c2", data: { type: "character", layer: 0 }, position: { x: 0, y: 0 } },
      { id: "n1", data: { layer: 1 }, position: { x: 0, y: 0 } },
    ];
    const result = autoLayout(nodes, []);
    const c1 = result.find((n) => n.id === "c1");
    const c2 = result.find((n) => n.id === "c2");
    const n1 = result.find((n) => n.id === "n1");
    // 角色垂直排列，不同 Y
    expect(c1.position.y).toBeLessThan(c2.position.y);
    // 角色在左侧（X 小于非角色）
    expect(c1.position.x).toBeLessThan(n1.position.x);
  });
});
