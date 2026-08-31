import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
  useRef,
} from "react";
import {
  ReactFlow,
  ReactFlowProvider,
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
import IsolatedNodePanel from "./nodes/IsolatedNodePanel";
import CustomEdge from "./edges/CustomEdge";
import CharacterRelationEdge from "./edges/CharacterRelationEdge";
import NodeDetailDrawer from "./nodes/NodeDetailDrawer";
import {
  fetchNodes,
  createNode,
  updateNode,
  fetchEdges,
  createEdge,
  updateEdge,
  deleteEdge,
  deleteNode,
  restoreCanvasSnapshot,
  fetchCharacterRelations,
  createCharacterRelation,
  deleteCharacterRelation,
} from "../lib/canvasApi";
import {
  applyEdgeLabelAvoidance,
  computeEdgeLayoutDiagnostics,
  applyEdgeHandles,
  resolveOptimalSides,
  edgeHandlesFromSides,
} from "../lib/edgeLayout";
import {
  buildGraphIndex,
  hasHierarchyChildren,
  hiddenDescendantSummary,
} from "../lib/canvasGraph";
import {
  projectVisibleGraph,
  toggleExpanded,
} from "../lib/canvasVisibility";
import { layoutVisibleGraph } from "../lib/canvasLayout";
import {
  CANVAS_MARQUEE_KEY_CODE,
  getMovedNodesFromSnapshot,
  persistNodePositionUpdates,
  shouldClearDrawerOnSelection,
} from "../lib/canvasDrag";
import {
  filterGraphAfterNodeRemoval,
  isCanvasDeleteKey,
  getDeletableSelectedNodeIds,
  shouldIgnoreCanvasKeyEvent,
} from "../lib/canvasDelete";
import {
  getStructuralEdgeStyle,
} from "../lib/structuralEdgeStyle";
import {
  applyNodeUpdateToData,
  buildFlowCharacterRelations,
  buildFlowEdges,
  canvasSnapshotKey,
  mergeRefreshedNodes,
  toCanvasSnapshot,
} from "../lib/canvasFlowAdapters";

const createNodeTypes = (
  onNodeClick,
  onFocusEdges,
  focusedNodeId,
  expandedNodeIds = new Set(),
  expandableNodeIds = new Set(),
  hiddenSummaryById = new Map(),
  onCollapseToggle,
) => ({
  custom: (props) => {
    const summary = hiddenSummaryById.get(props.id);
    return (
      <CustomNode
        {...props}
        onNodeClick={onNodeClick}
        onFocusEdges={onFocusEdges}
        isEdgesFocused={props.id === focusedNodeId}
        isExpanded={expandedNodeIds.has(props.id)}
        hasChildren={expandableNodeIds.has(props.id)}
        hiddenDescendantCount={summary?.total || 0}
        hiddenDescendantText={summary?.text || ""}
        onCollapseToggle={onCollapseToggle}
      />
    );
  },
});

const edgeTypes = {
  custom: CustomEdge,
  characterRelation: CharacterRelationEdge,
};

function isRelHandle(handleId) {
  return (handleId || "").startsWith("rel-");
}

export { applyNodeUpdateToData, mergeRefreshedNodes, toCanvasSnapshot };

const snapshotKey = canvasSnapshotKey;

const Canvas = forwardRef(function Canvas({ workId, onAddContext }, ref) {
  return (
    <ReactFlowProvider>
      <CanvasContent workId={workId} onAddContext={onAddContext} ref={ref} />
    </ReactFlowProvider>
  );
});

const CanvasContent = forwardRef(function CanvasContent({ workId, onAddContext }, ref) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [characterRelations, setCharacterRelations, onCharacterRelationsChange] = useEdgesState([]);
  const [showStructuralEdges, setShowStructuralEdges] = useState(true);
  const [showCharacterRelations, setShowCharacterRelations] = useState(true);
  const [contextMenu, setContextMenu] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [focusedNodeId, setFocusedNodeId] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [expandedNodeIds, setExpandedNodeIds] = useState(() => new Set());
  // 展开/收起时记录操作节点与操作前的坐标，用于布局后的整体平移补偿
  const [layoutAnchor, setLayoutAnchor] = useState(null);
  const contextMenuRef = useRef(null);
  const layoutPositionsRef = useRef(new Map());
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const characterRelationsRef = useRef(characterRelations);
  const undoStackRef = useRef([]);
  const dragSnapshotRef = useRef(null);
  const dragFinalizedRef = useRef(false);
  const isDraggingRef = useRef(false);
  const selectedNodeIdsRef = useRef([]);
  const restoringRef = useRef(false);
  const diagnosticsSentRef = useRef(new Map());

  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);

  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

  useEffect(() => {
    characterRelationsRef.current = characterRelations;
  }, [characterRelations]);

  const pushUndoSnapshot = useCallback((snapshot = null) => {
    const value = snapshot || toCanvasSnapshot(
      nodesRef.current,
      edgesRef.current,
      characterRelationsRef.current,
    );
    const stack = undoStackRef.current;
    if (stack.length && snapshotKey(stack[stack.length - 1]) === snapshotKey(value)) return;
    undoStackRef.current = [...stack.slice(-29), value];
  }, []);

  useEffect(() => {
    if (workId) {
      loadData();
    }
  }, [workId]);

  const loadData = async () => {
    if (!workId) return;

    setLoadError("");
    try {
      const [nodesData, edgesData, relationsData] = await Promise.all([
        fetchNodes(workId),
        fetchEdges(workId),
        fetchCharacterRelations(workId),
      ]);

      const flowNodes = mergeRefreshedNodes([], nodesData.nodes);
      const flowEdges = buildFlowEdges(edgesData, flowNodes);
      const flowRelations = buildFlowCharacterRelations(relationsData);

      setNodes(flowNodes);
      setEdges(flowEdges);
      setCharacterRelations(flowRelations);
      nodesRef.current = flowNodes;
      edgesRef.current = flowEdges;
      characterRelationsRef.current = flowRelations;
      undoStackRef.current = [];
      diagnosticsSentRef.current.clear();
    } catch (err) {
      console.error("Failed to load data:", err);
      setLoadError(err?.message || "加载画布失败");
    }
  };

  const refreshData = useCallback(async () => {
    if (!workId) return;
    setLoadError("");
    try {
      const [nodesData, edgesData, relationsData] = await Promise.all([
        fetchNodes(workId),
        fetchEdges(workId),
        fetchCharacterRelations(workId),
      ]);
      const nextNodes = mergeRefreshedNodes(nodesRef.current, nodesData.nodes);
      const nextEdges = buildFlowEdges(edgesData, nextNodes);
      const nextRelations = buildFlowCharacterRelations(relationsData);
      const previousSnapshot = toCanvasSnapshot(
        nodesRef.current,
        edgesRef.current,
        characterRelationsRef.current,
      );
      const nextSnapshot = toCanvasSnapshot(nextNodes, nextEdges, nextRelations);
      if (!restoringRef.current && snapshotKey(previousSnapshot) !== snapshotKey(nextSnapshot)) {
        pushUndoSnapshot(previousSnapshot);
      }
      nodesRef.current = nextNodes;
      edgesRef.current = nextEdges;
      characterRelationsRef.current = nextRelations;
      setNodes(nextNodes);
      setEdges(nextEdges);
      setCharacterRelations(nextRelations);
      // The detail drawer keeps its own selected-node state, so keep it in
      // sync when an agent update refreshes the canvas data.
      setSelectedNode((previousSelectedNode) => {
        if (!previousSelectedNode) return previousSelectedNode;
        const refreshedNode = nextNodes.find(
          (node) => node.id === previousSelectedNode.id,
        );
        return refreshedNode
          ? { id: refreshedNode.id, ...refreshedNode.data }
          : null;
      });
    } catch (err) {
      console.error("Failed to refresh data:", err);
      setLoadError(err?.message || "刷新画布失败，已保留当前内容");
    }
  }, [workId, setNodes, setEdges, setCharacterRelations, pushUndoSnapshot]);

  const undo = useCallback(async () => {
    if (!workId || restoringRef.current || undoStackRef.current.length === 0) return;
    const snapshot = undoStackRef.current[undoStackRef.current.length - 1];
    undoStackRef.current = undoStackRef.current.slice(0, -1);
    restoringRef.current = true;
    try {
      await restoreCanvasSnapshot(workId, snapshot);
      const restoredNodes = mergeRefreshedNodes([], snapshot.nodes.map((node) => ({
        ...node,
        title: node.title,
      })));
      const restoredEdges = buildFlowEdges({ edges: snapshot.edges }, restoredNodes);
      const restoredRelations = buildFlowCharacterRelations({
        relations: snapshot.character_relations || [],
      });
      nodesRef.current = restoredNodes;
      edgesRef.current = restoredEdges;
      characterRelationsRef.current = restoredRelations;
      setNodes(restoredNodes);
      setEdges(restoredEdges);
      setCharacterRelations(restoredRelations);
      setSelectedNode(null);
      setFocusedNodeId(null);
    } catch (err) {
      undoStackRef.current = [...undoStackRef.current, snapshot];
      console.error("Failed to undo canvas change:", err);
    } finally {
      restoringRef.current = false;
    }
  }, [workId, setNodes, setEdges, setCharacterRelations]);

  const removeNodesByIds = useCallback(async (nodeIds) => {
    const uniqueIds = [...new Set((nodeIds || []).filter(Boolean))];
    if (!uniqueIds.length) return;

    try {
      pushUndoSnapshot();
      await Promise.all(uniqueIds.map((id) => deleteNode(id)));

      const idSet = new Set(uniqueIds);
      setNodes((currentNodes) => {
        const next = filterGraphAfterNodeRemoval(uniqueIds, currentNodes, [], []).nodes;
        nodesRef.current = next;
        return next;
      });
      setEdges((currentEdges) => {
        const next = filterGraphAfterNodeRemoval(uniqueIds, [], currentEdges, []).edges;
        edgesRef.current = next;
        return next;
      });
      setCharacterRelations((currentRelations) => {
        const next = filterGraphAfterNodeRemoval(uniqueIds, [], [], currentRelations)
          .characterRelations;
        characterRelationsRef.current = next;
        return next;
      });

      selectedNodeIdsRef.current = selectedNodeIdsRef.current.filter((id) => !idSet.has(id));
      setSelectedNode((prev) => (prev && idSet.has(prev.id) ? null : prev));
    } catch (err) {
      console.error("Failed to delete nodes:", err);
      alert("删除节点失败");
    }
  }, [setNodes, setEdges, setCharacterRelations, pushUndoSnapshot]);

  const handleDeleteNode = useCallback(async (nodeData) => {
    const nodeId = nodeData?.id;
    if (!nodeId) return;
    await removeNodesByIds([nodeId]);
  }, [removeNodesByIds]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (shouldIgnoreCanvasKeyEvent(event)) return;

      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        undo();
        return;
      }

      if (isCanvasDeleteKey(event)) {
        const selectedIds = [...selectedNodeIdsRef.current];
        if (selectedIds.length === 0) return;
        event.preventDefault();
        removeNodesByIds(selectedIds);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [undo, removeNodesByIds]);

  const handleNodeUpdate = useCallback(async (nodeId, data) => {
    try {
      await updateNode(nodeId, data);
      // 本地更新画布节点显示
      setNodes((nds) => {
        const next = nds.map((n) =>
          n.id === nodeId
            ? { ...n, data: applyNodeUpdateToData(n.data, data) }
            : n
        );
        nodesRef.current = next;
        return next;
      });
      // 同步更新抽屉里的节点（即时显示新内容，含 chapter_elements）
      setSelectedNode((prev) =>
        prev && prev.id === nodeId ? applyNodeUpdateToData(prev, data) : prev
      );
    } catch (err) {
      console.error("Failed to update node:", err);
      alert("保存失败：" + (err?.message || "未知错误"));
    }
  }, [setNodes, updateNode]);

  const handleToggleLocked = useCallback(async (nodeData) => {
    const nodeId = nodeData?.id;
    if (!nodeId) return;
    const nextLocked = !nodeData.locked;
    try {
      await updateNode(nodeId, { locked: nextLocked });
      setNodes((nds) => {
        const next = nds.map((n) =>
          n.id === nodeId
            ? { ...n, draggable: !nextLocked, data: { ...n.data, locked: nextLocked } }
            : n
        );
        nodesRef.current = next;
        return next;
      });
      setSelectedNode((prev) =>
        prev && prev.id === nodeId
          ? { ...prev, locked: nextLocked }
          : prev
      );
    } catch (err) {
      console.error("Failed to toggle node lock:", err);
      alert("固定失败：" + (err?.message || "未知错误"));
    }
  }, [setNodes, updateNode]);

  useImperativeHandle(
    ref,
    () => ({
      refresh: refreshData,
      handleDeleteNode,
      undo,
    }),
    [refreshData, handleDeleteNode, undo]
  );

  const onConnect = useCallback(
    async (params) => {
      if (!workId) return;

      const isRel = isRelHandle(params.sourceHandle) && isRelHandle(params.targetHandle);
      const sourceNode = nodesRef.current.find((n) => n.id === params.source);
      const targetNode = nodesRef.current.find((n) => n.id === params.target);
      const handles = sourceNode && targetNode
        ? edgeHandlesFromSides(resolveOptimalSides(sourceNode, targetNode), { relation: isRel })
        : edgeHandlesFromSides({ source_side: "bottom", target_side: "top" }, { relation: isRel });

      try {
        pushUndoSnapshot();

        if (isRel) {
          const newRel = await createCharacterRelation(workId, {
            source_id: params.source,
            target_id: params.target,
            relation_type: "关系",
            label: "",
          });

          setCharacterRelations((eds) => {
            const next = addEdge(
              {
                ...params,
                ...handles,
                id: newRel.id,
                type: "characterRelation",
                label: newRel.relation_type,
                markerEnd: { type: MarkerType.ArrowClosed },
                data: {
                  isCharacterRelation: true,
                  relation_type: newRel.relation_type,
                  label: newRel.label || "",
                },
              },
              eds,
            );
            characterRelationsRef.current = next;
            return next;
          });
          return;
        }

        const edgeData = {
          source_id: params.source,
          target_id: params.target,
          edge_type: "uses",
          label: "",
        };

        const newEdge = await createEdge(workId, edgeData);

        setEdges((eds) => {
          const next = addEdge(
            {
              ...params,
              ...handles,
              id: newEdge.id,
              type: "custom",
              style: getStructuralEdgeStyle("uses", sourceNode?.data?.type),
              markerEnd: { type: MarkerType.ArrowClosed },
              data: { edge_type: "uses", extra_data: newEdge.extra_data || {} },
            },
            eds
          );
          edgesRef.current = next;
          return next;
        });
      } catch (err) {
        console.error("Failed to create connection:", err);
      }
    },
    [workId, setEdges, setCharacterRelations, pushUndoSnapshot]
  );

  const isValidConnection = useCallback((connection) => {
    const srcRel = isRelHandle(connection.sourceHandle);
    const tgtRel = isRelHandle(connection.targetHandle);
    const srcNode = nodesRef.current.find((n) => n.id === connection.source);
    const tgtNode = nodesRef.current.find((n) => n.id === connection.target);

    if (srcRel || tgtRel) {
      if (!srcRel || !tgtRel) return false;
      return srcNode?.data?.type === "character" && tgtNode?.data?.type === "character";
    }

    if (srcNode?.data?.type === "character" && tgtNode?.data?.type === "character") {
      return false;
    }
    return true;
  }, []);

  const onCombinedEdgesChange = useCallback(
    (changes) => {
      const structuralChanges = [];
      const relationChanges = [];
      const structuralRemovals = [];
      const relationRemovals = [];

      for (const change of changes) {
        const isRelation = change.id
          ? characterRelationsRef.current.some((e) => e.id === change.id)
          : false;

        if (change.type === "remove" && change.id) {
          if (isRelation) {
            relationRemovals.push(change);
            continue;
          }
          structuralRemovals.push(change);
          continue;
        }

        if (isRelation) relationChanges.push(change);
        else structuralChanges.push(change);
      }

      if (structuralChanges.length) onEdgesChange(structuralChanges);
      if (relationChanges.length) onCharacterRelationsChange(relationChanges);

      if (structuralRemovals.length || relationRemovals.length) {
        pushUndoSnapshot();
        Promise.all([
          ...structuralRemovals.map((change) => deleteEdge(change.id)),
          ...relationRemovals.map((change) => deleteCharacterRelation(change.id)),
        ])
          .then(() => {
            if (structuralRemovals.length) onEdgesChange(structuralRemovals);
            if (relationRemovals.length) onCharacterRelationsChange(relationRemovals);
          })
          .catch((err) => {
            console.error("Failed to delete canvas connection:", err);
            alert("删除连线失败，画布已保留原状态");
          });
      }
    },
    [onEdgesChange, onCharacterRelationsChange, pushUndoSnapshot],
  );

  const onPaneClick = useCallback(() => {
    setContextMenu(null);
    setFocusedNodeId(null);
    setSelectedNode(null);
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
      pushUndoSnapshot();
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

      setNodes((nds) => {
        const next = [
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
        ];
        nodesRef.current = next;
        return next;
      });
    } catch (err) {
      console.error("Failed to create node:", err);
    }
  };

  const handleDeleteEdge = async (edgeId) => {
    try {
      pushUndoSnapshot();
      await deleteEdge(edgeId);
      setEdges((eds) => {
        const next = eds.filter((e) => e.id !== edgeId);
        edgesRef.current = next;
        return next;
      });
    } catch (err) {
      console.error("Failed to delete edge:", err);
    }
  };

  const handleRefresh = () => {
    refreshData();
  };

  const handleNodeClick = useCallback((nodeData) => {
    setSelectedNode(nodeData);
  }, []);

  const chapterNodes = useMemo(
    () => nodes
      .filter((flowNode) => flowNode.data?.type === "chapter")
      .map((flowNode) => ({ id: flowNode.id, ...flowNode.data })),
    [nodes],
  );

  const handleChapterNavigate = useCallback((chapterNode) => {
    setSelectedNode(chapterNode);
  }, []);

  const handleSelectionChange = useCallback(({ nodes: selectedNodes }) => {
    selectedNodeIdsRef.current = getDeletableSelectedNodeIds(
      (selectedNodes || []).map((node) => ({ ...node, selected: true })),
    );
    if (shouldClearDrawerOnSelection(selectedNodes.length, isDraggingRef.current)) {
      setSelectedNode(null);
    }
  }, []);

  const handleFocusEdges = useCallback((nodeId) => {
    setFocusedNodeId((current) => current === nodeId ? null : nodeId);
  }, []);

  const handleCloseDrawer = useCallback(() => {
    setSelectedNode(null);
  }, []);

  const beginDragSnapshot = useCallback(() => {
    dragFinalizedRef.current = false;
    isDraggingRef.current = true;
    dragSnapshotRef.current = toCanvasSnapshot(
      nodesRef.current,
      edgesRef.current,
      characterRelationsRef.current,
    );
    setIsDragging(true);
  }, []);

  const finishDragPersist = useCallback(() => {
    if (dragFinalizedRef.current) return;
    dragFinalizedRef.current = true;
    isDraggingRef.current = false;
    setIsDragging(false);

    const snapshot = dragSnapshotRef.current;
    if (snapshot) {
      pushUndoSnapshot(snapshot);
      dragSnapshotRef.current = null;
    }

    const movedNodes = getMovedNodesFromSnapshot(snapshot, nodesRef.current);
    if (movedNodes.length === 0) return;

    persistNodePositionUpdates(movedNodes, updateNode).catch((err) => {
      console.error("Failed to persist node positions:", err);
    });
  }, [pushUndoSnapshot]);

  const handleNodeDragStart = useCallback(() => {
    beginDragSnapshot();
  }, [beginDragSnapshot]);

  const handleNodeDragStop = useCallback(() => {
    finishDragPersist();
  }, [finishDragPersist]);

  const handleSelectionDragStart = useCallback(() => {
    beginDragSnapshot();
  }, [beginDragSnapshot]);

  const handleSelectionDragStop = useCallback(() => {
    finishDragPersist();
  }, [finishDragPersist]);

  // ── 可见子图投影与动态布局 ──
  // nodes / edges 保存完整语义图；下面派生出当前视图，隐藏节点不会被丢弃。
  const graphIndex = useMemo(() => buildGraphIndex(nodes, edges), [nodes, edges]);

  const visibleGraph = useMemo(
    () => projectVisibleGraph({
      index: graphIndex,
      expandedNodeIds,
      focusNodeId: focusedNodeId,
      selectedNodeId: selectedNode?.id ?? null,
    }),
    [graphIndex, expandedNodeIds, focusedNodeId, selectedNode?.id],
  );

  const layoutPositions = useMemo(
    () => layoutVisibleGraph({
      index: graphIndex,
      visibleNodeIds: visibleGraph.visibleNodeIds,
      depthById: visibleGraph.depthById,
      satelliteAnchorById: visibleGraph.satelliteAnchorById,
      previousPositions: layoutAnchor?.positions ?? null,
      anchorNodeId: layoutAnchor?.nodeId ?? null,
    }),
    [graphIndex, visibleGraph, layoutAnchor],
  );

  useEffect(() => {
    layoutPositionsRef.current = layoutPositions;
  }, [layoutPositions]);

  const expandableNodeIds = useMemo(() => {
    const ids = new Set();
    for (const node of visibleGraph.visibleNodes) {
      if (hasHierarchyChildren(graphIndex, node.id)) ids.add(node.id);
    }
    return ids;
  }, [graphIndex, visibleGraph]);

  const hiddenSummaryById = useMemo(() => {
    const summaries = new Map();
    for (const nodeId of expandableNodeIds) {
      summaries.set(
        nodeId,
        hiddenDescendantSummary(graphIndex, nodeId, visibleGraph.visibleNodeIds),
      );
    }
    return summaries;
  }, [graphIndex, expandableNodeIds, visibleGraph]);

  const handleCollapseToggle = useCallback((nodeId) => {
    setLayoutAnchor({
      nodeId,
      positions: new Map(layoutPositionsRef.current),
    });
    setExpandedNodeIds((prev) => toggleExpanded(prev, nodeId));
  }, []);

  const displayedNodes = useMemo(
    () => visibleGraph.visibleNodes.map((node) => ({
      ...node,
      position: layoutPositions.get(node.id) ?? node.position,
      // 位置由可见子图推导，手动拖动不参与布局
      draggable: false,
    })),
    [visibleGraph, layoutPositions],
  );

  // 连线的连接点与标签避让必须基于布局后的坐标，否则会指向节点的旧位置
  const visibleStructuralEdges = useMemo(
    () => {
      if (!showStructuralEdges) return [];
      return focusedNodeId
        ? visibleGraph.visibleEdges.filter(
          (edge) => edge.source === focusedNodeId || edge.target === focusedNodeId,
        )
        : visibleGraph.visibleEdges;
    },
    [visibleGraph, focusedNodeId, showStructuralEdges],
  );

  const visibleCharacterRelations = useMemo(
    () => {
      if (!showCharacterRelations) return [];
      const onCanvas = characterRelations.filter(
        (edge) =>
          visibleGraph.visibleNodeIds.has(edge.source) &&
          visibleGraph.visibleNodeIds.has(edge.target),
      );
      return focusedNodeId
        ? onCanvas.filter(
          (edge) => edge.source === focusedNodeId || edge.target === focusedNodeId,
        )
        : onCanvas;
    },
    [characterRelations, visibleGraph, focusedNodeId, showCharacterRelations],
  );

  const displayStructuralEdges = useMemo(
    () => applyEdgeLabelAvoidance(
      displayedNodes,
      applyEdgeHandles(displayedNodes, visibleStructuralEdges),
    ),
    [displayedNodes, visibleStructuralEdges],
  );

  const displayCharacterRelations = useMemo(
    () => applyEdgeHandles(displayedNodes, visibleCharacterRelations, { relation: true }),
    [displayedNodes, visibleCharacterRelations],
  );

  const displayedEdges = useMemo(
    () => [...displayStructuralEdges, ...displayCharacterRelations],
    [displayStructuralEdges, displayCharacterRelations],
  );

  const nodeTypes = useMemo(
    () => createNodeTypes(
      handleNodeClick,
      handleFocusEdges,
      focusedNodeId,
      expandedNodeIds,
      expandableNodeIds,
      hiddenSummaryById,
      handleCollapseToggle,
    ),
    [
      handleNodeClick,
      handleFocusEdges,
      focusedNodeId,
      expandedNodeIds,
      expandableNodeIds,
      hiddenSummaryById,
      handleCollapseToggle,
    ],
  );

  useEffect(() => {
    if (!workId || !nodes.length || !edges.length || restoringRef.current) return undefined;
    const diagnostics = computeEdgeLayoutDiagnostics(nodes, edges);
    const pending = diagnostics.filter((item) => {
      const previousVersion = diagnosticsSentRef.current.get(item.edge_id);
      return previousVersion !== item.layout_version;
    });
    if (!pending.length) return undefined;

    const timer = window.setTimeout(async () => {
      const edgeMap = new Map(edgesRef.current.map((edge) => [edge.id, edge]));
      await Promise.all(pending.map(async (diagnostic) => {
        const edge = edgeMap.get(diagnostic.edge_id);
        if (!edge) return;
        diagnosticsSentRef.current.set(
          diagnostic.edge_id,
          diagnostic.layout_version,
        );
        try {
          await updateEdge(diagnostic.edge_id, {
            extra_data: {
              ...(edge.data?.extra_data || {}),
              layout_diagnostics: diagnostic,
            },
          });
        } catch (error) {
          diagnosticsSentRef.current.delete(diagnostic.edge_id);
          console.error("Failed to persist edge layout diagnostics:", error);
        }
      }));
    }, 700);
    return () => window.clearTimeout(timer);
  }, [workId, nodes, edges]);

  return (
    <div className="w-full h-full flex relative">
      <div className="flex-1 relative">
        {loadError && (
          <div className="absolute left-1/2 top-3 z-20 -translate-x-1/2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 shadow-sm">
            {loadError}
          </div>
        )}
        <div className="absolute top-3 left-3 z-10 flex gap-2">
          <button
            type="button"
            onClick={() => setShowStructuralEdges((v) => !v)}
            className={`rounded px-2 py-1 text-xs border shadow-sm transition-colors ${
              showStructuralEdges
                ? "bg-white border-slate-300 text-slate-700"
                : "bg-slate-100 border-slate-200 text-slate-400"
            }`}
          >
            结构线
          </button>
          <button
            type="button"
            onClick={() => setShowCharacterRelations((v) => !v)}
            className={`rounded px-2 py-1 text-xs border shadow-sm transition-colors ${
              showCharacterRelations
                ? "bg-rose-50 border-rose-200 text-rose-700"
                : "bg-slate-100 border-slate-200 text-slate-400"
            }`}
          >
            角色关系线
          </button>
        </div>
        <ReactFlow
          nodes={displayedNodes}
          edges={displayedEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onCombinedEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onPaneClick={onPaneClick}
          onPaneContextMenu={onPaneContextMenu}
          onSelectionChange={handleSelectionChange}
          onNodeDragStart={handleNodeDragStart}
          onNodeDragStop={handleNodeDragStop}
          onSelectionDragStart={handleSelectionDragStart}
          onSelectionDragStop={handleSelectionDragStop}
          selectionKeyCode={CANVAS_MARQUEE_KEY_CODE}
          multiSelectionKeyCode={CANVAS_MARQUEE_KEY_CODE}
          deleteKeyCode={null}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
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
              { type: "volume", icon: "📚", label: "卷", color: "text-indigo-600" },
              { type: "plot", icon: "⚡", label: "情节", color: "text-orange-600" },
              { type: "chapter", icon: "📖", label: "章节", color: "text-green-600" },
              { type: "character", icon: "👤", label: "角色", color: "text-pink-600" },
              { type: "worldbuilding", icon: "🌍", label: "世界观", color: "text-purple-600" },
              { type: "note", icon: "📝", label: "笔记", color: "text-fuchsia-600" },
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

      {/* 全局节点入口：禁止连线的孤立节点不进画布，避免铺满可视区域 */}
      <IsolatedNodePanel nodes={nodes} onSelect={handleNodeClick} />

      {/* 节点详情抽屉 */}
      <NodeDetailDrawer node={selectedNode} onClose={handleCloseDrawer} onDelete={handleDeleteNode} onUpdate={handleNodeUpdate} onAddContext={onAddContext} onToggleLocked={handleToggleLocked} chapterNodes={chapterNodes} onChapterNavigate={handleChapterNavigate} />
    </div>
  );
});

export { Canvas };
export default Canvas;
