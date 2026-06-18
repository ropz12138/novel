import { forwardRef, useCallback, useEffect, useImperativeHandle, useState, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import CustomNode from "./nodes/CustomNode";
import NodeDetailDrawer from "./nodes/NodeDetailDrawer";
import {
  fetchNodes,
  createNode,
  updateNode,
  fetchEdges,
  createEdge,
  deleteEdge,
  deleteNode,
} from "../lib/canvasApi";

const createNodeTypes = (onNodeClick) => ({
  custom: (props) => <CustomNode {...props} onNodeClick={onNodeClick} />,
});

const edgeStyles = {
  uses: { stroke: "#3b82f6", strokeWidth: 2 },
  hints: { stroke: "#a855f7", strokeWidth: 1.5, strokeDasharray: "5,5" },
  conflict: { stroke: "#ef4444", strokeWidth: 2 },
  inherits: { stroke: "#22c55e", strokeWidth: 2 },
  contains: { stroke: "#f59e0b", strokeWidth: 2, strokeDasharray: "8,4" },
  reverses: { stroke: "#f97316", strokeWidth: 2, strokeDasharray: "10,5" },
  character_appears: { stroke: "#ec4899", strokeWidth: 1.5 },
  mood: { stroke: "#6366f1", strokeWidth: 1.5 },
  forbids_reveal: { stroke: "#dc2626", strokeWidth: 2.5 },
  _default: { stroke: "#94a3b8", strokeWidth: 1.5 },
};

// 获取边样式：保留类型使用预设样式，自然语言类型使用默认样式
function getEdgeStyle(edgeType) {
  return edgeStyles[edgeType] || edgeStyles._default;
}

// 自动布局：按 layer 分行（同 layer 同 Y，layer 数字小的在上），同行按顺序排 X。
// 不依赖边（关系为自然语言，不参与布局）。已手动定位的节点跳过。
export function autoLayout(nodes, edges) {
  if (nodes.length === 0) return nodes;

  const NODE_W = 200;
  const H_GAP = 60;
  const LAYER_HEIGHT = 200;
  const CHAR_W = 200;
  const CHAR_GAP = 20;
  const LEFT_PANEL_W = 260;

  const characterNodes = [];
  const otherNodes = [];
  for (const n of nodes) {
    if (n.data?.manuallyPositioned) continue;
    if (n.data?.type === "character") {
      characterNodes.push(n);
    } else {
      otherNodes.push(n);
    }
  }

  // 角色垂直排列在左侧
  const pos = {};
  characterNodes.forEach((n, i) => {
    pos[n.id] = { x: -LEFT_PANEL_W, y: i * (CHAR_W + CHAR_GAP) };
  });

  // 非角色按 layer 分行，整体右移
  const byLayer = new Map();
  for (const n of otherNodes) {
    const layer = n.data?.layer ?? 0;
    if (!byLayer.has(layer)) byLayer.set(layer, []);
    byLayer.get(layer).push(n);
  }
  const layers = [...byLayer.keys()].sort((a, b) => a - b);

  for (const layer of layers) {
    const group = byLayer.get(layer);
    const y = layer * LAYER_HEIGHT;
    const totalWidth = group.length * NODE_W + (group.length - 1) * H_GAP;
    let x = -totalWidth / 2 + LEFT_PANEL_W;
    for (const n of group) {
      pos[n.id] = { x, y };
      x += NODE_W + H_GAP;
    }
  }

  return nodes.map((n) => ({
    ...n,
    position: n.data?.manuallyPositioned ? n.position : (pos[n.id] || n.position),
  }));
}

export function mergeRefreshedNodes(currentNodes, fetchedRawNodes) {
  const currentById = new Map(currentNodes.map((n) => [n.id, n]));

  return fetchedRawNodes.map((n) => {
    const fetchedData = {
      type: n.type,
      label: n.title,
      content: n.content,
      extra_data: n.extra_data,
      layer: n.layer ?? 0,
    };
    const existing = currentById.get(n.id);
    if (existing) {
      return {
        id: n.id,
        type: "custom",
        position: existing.position,
        data: { ...fetchedData, manuallyPositioned: existing.data?.manuallyPositioned ?? false },
      };
    }
    return {
      id: n.id,
      type: "custom",
      position: { x: n.position_x, y: n.position_y },
      data: { ...fetchedData, manuallyPositioned: n.manually_positioned ?? false },
    };
  });
}

function buildFlowEdges(edgesData) {
  return edgesData.edges.map((e) => ({
    id: e.id,
    source: e.source_id,
    target: e.target_id,
    type: "smoothstep",
    animated: e.edge_type === "hints",
    label: e.label,
    style: getEdgeStyle(e.edge_type),
    markerEnd: { type: MarkerType.ArrowClosed },
    data: { edge_type: e.edge_type },
  }));
}

const Canvas = forwardRef(function Canvas({ workId }, ref) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [contextMenu, setContextMenu] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const contextMenuRef = useRef(null);

  useEffect(() => {
    if (workId) {
      loadData();
    }
  }, [workId]);

  const loadData = async () => {
    if (!workId) return;

    try {
      const [nodesData, edgesData] = await Promise.all([
        fetchNodes(workId),
        fetchEdges(workId),
      ]);

      const flowNodes = nodesData.nodes.map((n) => ({
        id: n.id,
        type: "custom",
        position: { x: n.position_x, y: n.position_y },
        data: {
          type: n.type,
          label: n.title,
          content: n.content,
          extra_data: n.extra_data,
          layer: n.layer ?? 0,
          manuallyPositioned: n.manually_positioned ?? false,
        },
      }));

      const flowEdges = edgesData.edges.map((e) => ({
        id: e.id,
        source: e.source_id,
        target: e.target_id,
        type: "smoothstep",
        animated: e.edge_type === "hints",
        label: e.label,
        style: getEdgeStyle(e.edge_type),
        markerEnd: { type: MarkerType.ArrowClosed },
        data: { edge_type: e.edge_type },
      }));

      const layoutedNodes = autoLayout(flowNodes, flowEdges);
      setNodes(layoutedNodes);
      setEdges(flowEdges);
    } catch (err) {
      console.error("Failed to load data:", err);
    }
  };

  const refreshData = useCallback(async () => {
    if (!workId) return;
    try {
      const [nodesData, edgesData] = await Promise.all([
        fetchNodes(workId),
        fetchEdges(workId),
      ]);
      setNodes((prev) => {
        const merged = mergeRefreshedNodes(prev, nodesData.nodes);
        return autoLayout(merged, edgesData.edges);
      });
      setEdges(buildFlowEdges(edgesData));
    } catch (err) {
      console.error("Failed to refresh data:", err);
    }
  }, [workId, setNodes, setEdges]);

  const handleDeleteNode = useCallback(async (nodeData) => {
    const nodeId = nodeData?.id;
    if (!nodeId) return;
    try {
      await deleteNode(nodeId);
      setNodes((nds) => nds.filter((n) => n.id !== nodeId));
      setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
      setSelectedNode(null);
    } catch (err) {
      console.error("Failed to delete node:", err);
      alert("删除节点失败");
    }
  }, [setNodes, setEdges]);

  useImperativeHandle(ref, () => ({ refresh: refreshData, handleDeleteNode }), [refreshData, handleDeleteNode]);

  const onConnect = useCallback(
    async (params) => {
      if (!workId) return;

      try {
        const edgeData = {
          source_id: params.source,
          target_id: params.target,
          edge_type: "uses",
          label: "",
        };

        const newEdge = await createEdge(workId, edgeData);

        setEdges((eds) =>
          addEdge(
            {
              ...params,
              id: newEdge.id,
              type: "smoothstep",
              style: edgeStyles.uses,
              markerEnd: { type: MarkerType.ArrowClosed },
              data: { edge_type: "uses" },
            },
            eds
          )
        );
      } catch (err) {
        console.error("Failed to create edge:", err);
      }
    },
    [workId, setEdges]
  );

  const onPaneClick = useCallback(() => {
    setContextMenu(null);
  }, []);

  const onPaneContextMenu = useCallback((event) => {
    event.preventDefault();
    // 获取点击位置（相对于画布）
    const bounds = event.target.closest('.react-flow')?.getBoundingClientRect();
    if (!bounds) return;
    setContextMenu({
      x: event.clientX - bounds.left,
      y: event.clientY - bounds.top,
    });
  }, []);

  const closeContextMenu = useCallback(() => {
    setContextMenu(null);
  }, []);

  useEffect(() => {
    const handleClick = (e) => {
      if (contextMenuRef.current && !contextMenuRef.current.contains(e.target)) {
        setContextMenu(null);
      }
    };
    if (contextMenu) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [contextMenu]);

  const handleAddNode = async (type) => {
    if (!workId) return;

    try {
      let maxX = 50;
      nodes.forEach((n) => {
        if (n.position.x > maxX) maxX = n.position.x;
      });

      const newNodeData = {
        type,
        title: `新${type}节点`,
        content: "",
        position_x: maxX + 350,
        position_y: 200,
      };

      const created = await createNode(workId, newNodeData);

      setNodes((nds) => [
        ...nds,
        {
          id: created.id,
          type: "custom",
          position: { x: created.position_x, y: created.position_y },
          data: {
            type: created.type,
            label: created.title,
            content: created.content,
            extra_data: created.extra_data,
          },
        },
      ]);
    } catch (err) {
      console.error("Failed to create node:", err);
    }
  };

  const handleDeleteEdge = async (edgeId) => {
    try {
      await deleteEdge(edgeId);
      setEdges((eds) => eds.filter((e) => e.id !== edgeId));
    } catch (err) {
      console.error("Failed to delete edge:", err);
    }
  };

  const handleAutoLayout = async () => {
    const layoutedNodes = autoLayout(nodes, edges);
    setNodes(layoutedNodes);

    for (const node of layoutedNodes) {
      try {
        await updateNode(node.id, {
          position_x: node.position.x,
          position_y: node.position.y,
        });
      } catch (err) {
        console.error("Failed to update node position:", err);
      }
    }
  };

  const handleRefresh = () => {
    loadData();
  };

  const handleNodeClick = useCallback((nodeData) => {
    setSelectedNode(nodeData);
  }, []);

  const handleCloseDrawer = useCallback(() => {
    setSelectedNode(null);
  }, []);

  const handleNodeDragStop = useCallback((_, node) => {
    // 手动拖动后标记，autoLayout 不再覆盖；并持久化坐标
    setNodes((nds) =>
      nds.map((n) =>
        n.id === node.id
          ? { ...n, position: node.position, data: { ...n.data, manuallyPositioned: true } }
          : n
      )
    );
    updateNode(node.id, {
      position_x: node.position.x,
      position_y: node.position.y,
      manually_positioned: true,
    }).catch((err) => console.error("Failed to persist node position:", err));
  }, [setNodes]);

  const nodeTypes = createNodeTypes(handleNodeClick);

  return (
    <div className="w-full h-full flex">
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onPaneClick={onPaneClick}
          onPaneContextMenu={onPaneContextMenu}
          onNodeDragStop={handleNodeDragStop}
          nodeTypes={nodeTypes}
          fitView
          attributionPosition="bottom-left"
        >
          <Background />
          <Controls />
          <MiniMap
            nodeStrokeWidth={3}
            zoomable
            pannable
            style={{ height: 120, width: 180 }}
          />
        </ReactFlow>

        {/* 右键菜单 */}
        {contextMenu && (
          <div
            ref={contextMenuRef}
            className="absolute z-50 bg-white rounded-lg shadow-lg border border-gray-200 py-1 min-w-[160px]"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <div className="px-3 py-1.5 text-xs font-medium text-gray-400 border-b border-gray-100">
              添加节点
            </div>
            {[
              { type: "outline", icon: "📋", label: "大纲", color: "text-blue-600" },
              { type: "idea", icon: "💡", label: "灵感", color: "text-yellow-600" },
              { type: "chapter", icon: "📖", label: "章节", color: "text-green-600" },
              { type: "character", icon: "👤", label: "角色", color: "text-pink-600" },
              { type: "foreshadow", icon: "🔮", label: "伏笔", color: "text-teal-600" },
              { type: "conflict", icon: "⚔️", label: "冲突", color: "text-red-600" },
              { type: "worldbuilding", icon: "🌍", label: "世界观", color: "text-teal-600" },
            ].map((item) => (
              <button
                key={item.type}
                onClick={() => {
                  handleAddNode(item.type);
                  closeContextMenu();
                }}
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-gray-50 transition-colors ${item.color}`}
              >
                <span>{item.icon}</span>
                <span>{item.label}</span>
              </button>
            ))}
            <div className="border-t border-gray-100 mt-1 pt-1">
              <button
                onClick={() => {
                  handleRefresh();
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
              >
                <span>🔄</span>
                <span>刷新</span>
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 节点详情抽屉 */}
      <NodeDetailDrawer node={selectedNode} onClose={handleCloseDrawer} onDelete={handleDeleteNode} />
    </div>
  );
});

export { Canvas };
export default Canvas;
