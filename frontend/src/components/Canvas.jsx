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

// 自动布局函数：自底向上，子节点居中于父节点下方，父节点间距根据子树宽度调整
function autoLayout(nodes, edges) {
  if (nodes.length === 0) return nodes;

  const NODE_W = 200;
  const H_GAP = 60;
  const V_GAP = 100;

  const getEdgeType = (e) => e.data?.edge_type || e.edge_type || e.type;

  // ========== 诊断日志：输入数据 ==========
  console.group("[autoLayout] 输入数据");
  console.table(nodes.map(n => ({ id: n.id, type: n.data?.type, label: n.data?.label, pos: `${n.position.x},${n.position.y}` })));
  console.table(edges.map(e => ({ id: e.id, source: e.source, target: e.target, type: getEdgeType(e) })));
  console.groupEnd();

  // 构建边映射
  const containsEdges = edges.filter(e => getEdgeType(e) === "contains");
  const inheritsEdges = edges.filter(e => getEdgeType(e) === "inherits");
  const containsTargetIds = new Set(containsEdges.map(e => e.target));

  // 构建父子关系映射（排除角色节点，角色节点单独布局）
  const childrenMap = {};
  containsEdges.forEach(edge => {
    const childNode = nodes.find(n => n.id === edge.target);
    if (childNode && childNode.data?.type !== "character") {
      if (!childrenMap[edge.source]) childrenMap[edge.source] = [];
      childrenMap[edge.source].push(childNode);
    }
  });

  // 找到主链起始节点
  const targetIds = new Set(inheritsEdges.map(e => e.target));
  const sourceIds = new Set(inheritsEdges.map(e => e.source));
  let startNode = nodes.find(n => sourceIds.has(n.id) && !targetIds.has(n.id) && !containsTargetIds.has(n.id));
  if (!startNode) startNode = nodes.find(n => sourceIds.has(n.id) && !targetIds.has(n.id));
  if (!startNode) startNode = nodes[0];

  // 按照 inherits 边排序子节点
  function sortByInherits(nodeList) {
    if (nodeList.length <= 1) return nodeList;
    const edges = inheritsEdges.filter(e =>
      nodeList.some(n => n.id === e.source) && nodeList.some(n => n.id === e.target)
    );
    if (edges.length === 0) return nodeList;
    const tIds = new Set(edges.map(e => e.target));
    let start = nodeList.find(n => !tIds.has(n.id));
    if (!start) start = nodeList[0];
    const ordered = [start];
    const visited = new Set([start.id]);
    let cur = start;
    while (ordered.length < nodeList.length) {
      const nextEdge = edges.find(e => e.source === cur.id && !visited.has(e.target));
      if (nextEdge) {
        const nextNode = nodeList.find(n => n.id === nextEdge.target);
        if (nextNode) {
          ordered.push(nextNode);
          visited.add(nextNode.id);
          cur = nextNode;
          continue;
        }
      }
      nodeList.forEach(n => { if (!visited.has(n.id)) { ordered.push(n); visited.add(n.id); } });
      break;
    }
    return ordered;
  }

  // 构建主链
  const mainChain = [];
  const visited = new Set();
  let current = startNode;
  while (current && !visited.has(current.id)) {
    mainChain.push(current);
    visited.add(current.id);
    const nextEdge = inheritsEdges.find(e => e.source === current.id);
    current = nextEdge ? nodes.find(n => n.id === nextEdge.target) : null;
  }

  const otherNodes = nodes.filter(n => !visited.has(n.id));

  // ========== 诊断日志：主链 vs 其他 ==========
  console.group("[autoLayout] 节点分类");
  console.log("inherits 边数量:", inheritsEdges.length);
  console.log("起始节点:", startNode?.id, startNode?.data?.type, startNode?.data?.label);
  console.log("主链节点:", mainChain.map(n => `${n.data?.type}(${n.data?.label})`).join(" → "));
  console.log("其他节点:", otherNodes.map(n => `${n.data?.type}(${n.data?.label})`).join(", "));
  console.groupEnd();

  // ========== 诊断日志：contains 边映射 ==========
  console.group("[autoLayout] contains 边映射");
  console.log("contains 边数量:", containsEdges.length);
  for (const [parentId, children] of Object.entries(childrenMap)) {
    const parentNode = nodes.find(n => n.id === parentId);
    console.log(`  ${parentNode?.data?.type}(${parentNode?.data?.label}) → [${children.map(c => `${c.data?.type}(${c.data?.label})`).join(", ")}]`);
  }
  console.groupEnd();

  // 计算子树宽度（自底向上）
  function getSubtreeWidth(nodeId) {
    const children = childrenMap[nodeId] || [];
    if (children.length === 0) return NODE_W;
    const childrenTotalWidth = children.reduce((sum, child) => sum + getSubtreeWidth(child.id), 0) + H_GAP * (children.length - 1);
    return Math.max(NODE_W, childrenTotalWidth);
  }

  // 递归布局节点及其子节点
  const pos = {};
  function layoutNode(nodeId, centerX, y) {
    const children = childrenMap[nodeId] || [];
    pos[nodeId] = { x: centerX - NODE_W / 2, y };
    visited.add(nodeId);

    if (children.length === 0) return;

    const sorted = sortByInherits(children);
    const childWidths = sorted.map(child => getSubtreeWidth(child.id));
    const totalChildrenWidth = childWidths.reduce((sum, w) => sum + w, 0) + H_GAP * (sorted.length - 1);

    let childStartX = centerX - totalChildrenWidth / 2;
    sorted.forEach((child, i) => {
      const childCenterX = childStartX + childWidths[i] / 2;
      layoutNode(child.id, childCenterX, y + NODE_W + V_GAP);
      childStartX += childWidths[i] + H_GAP;
    });
  }

  // 布局主链：根据子树宽度调整间距
  let mainChainX = 50;
  let mainChainMinX = Infinity;
  let mainChainMaxX = 0;
  mainChain.forEach(node => {
    const subtreeWidth = getSubtreeWidth(node.id);
    const centerX = mainChainX + subtreeWidth / 2;
    layoutNode(node.id, centerX, 50);
    mainChainMinX = Math.min(mainChainMinX, mainChainX);
    mainChainMaxX = Math.max(mainChainMaxX, mainChainX + subtreeWidth);
    mainChainX += subtreeWidth + H_GAP;
  });

  // 角色节点放在整体布局的左侧，纵向排列
  const characterNodes = otherNodes.filter(n => n.data?.type === "character");
  const nonCharacterNodes = otherNodes.filter(n => n.data?.type !== "character");

  const charX = mainChainMinX - NODE_W - H_GAP * 2;
  let cy = 50;
  characterNodes.forEach(node => {
    if (!pos[node.id]) {
      pos[node.id] = { x: charX, y: cy };
      cy += NODE_W + V_GAP;
    }
  });

  // 孤立节点放在整体布局的下方
  let ox = mainChainMinX;
  nonCharacterNodes.forEach(node => {
    if (!pos[node.id]) {
      pos[node.id] = { x: ox, y: 50 + (NODE_W + V_GAP) * 3 };
      ox += NODE_W + H_GAP;
    }
  });

  // ========== 诊断日志：最终坐标 ==========
  console.group("[autoLayout] 最终坐标");
  nodes.forEach(node => {
    const p = pos[node.id] || node.position;
    const category = mainChain.some(m => m.id === node.id) ? "主链"
      : characterNodes.some(c => c.id === node.id) ? "角色"
      : "孤立";
    console.log(`  [${category}] ${node.data?.type}(${node.data?.label}) → x:${p.x}, y:${p.y}`);
  });
  console.groupEnd();

  return nodes.map(node => ({ ...node, position: pos[node.id] || node.position }));
}

export function mergeRefreshedNodes(currentNodes, fetchedRawNodes) {
  const currentById = new Map(currentNodes.map((n) => [n.id, n]));

  return fetchedRawNodes.map((n) => {
    const fetchedData = {
      type: n.type,
      label: n.title,
      content: n.content,
      extra_data: n.extra_data,
    };
    const existing = currentById.get(n.id);
    if (existing) {
      return {
        id: n.id,
        type: "custom",
        position: existing.position,
        data: fetchedData,
      };
    }
    return {
      id: n.id,
      type: "custom",
      position: { x: n.position_x, y: n.position_y },
      data: fetchedData,
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

      setNodes(flowNodes);
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
      setNodes((prev) => mergeRefreshedNodes(prev, nodesData.nodes));
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
              { type: "macro_outline", icon: "🏗️", label: "宏观大纲", color: "text-red-600" },
              { type: "meso_outline", icon: "📋", label: "中纲", color: "text-orange-600" },
              { type: "micro_outline", icon: "📝", label: "小纲", color: "text-amber-600" },
              { type: "idea", icon: "💡", label: "灵感", color: "text-yellow-600" },
              { type: "chapter", icon: "📖", label: "章节", color: "text-green-600" },
              { type: "character", icon: "👤", label: "角色", color: "text-pink-600" },
              { type: "foreshadow", icon: "🔮", label: "伏笔", color: "text-teal-600" },
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
                  handleAutoLayout();
                  closeContextMenu();
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-sm text-purple-600 hover:bg-gray-50 transition-colors"
              >
                <span>📐</span>
                <span>自动布局</span>
              </button>
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
