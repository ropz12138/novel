import { MarkerType } from "@xyflow/react";
import { flowNodeDimensionsFromRaw } from "./nodeDimensions";
import {
  getStructuralEdgeStyle,
  nodeTypeByIdFromFlowNodes,
  nodeTypeByIdFromRawNodes,
} from "./structuralEdgeStyle";

export function applyNodeUpdateToData(previous, update) {
  if (!previous) return previous;
  const next = {
    ...previous,
    label: update.title ?? previous.label,
    content: update.content ?? previous.content,
  };
  if (update.chapter_elements !== undefined) {
    next.extra_data = {
      ...(previous.extra_data || {}),
      chapter_elements: update.chapter_elements,
    };
  }
  return next;
}

export function mergeRefreshedNodes(_currentNodes, fetchedRawNodes) {
  return fetchedRawNodes.map((node) => ({
    id: node.id,
    type: "custom",
    position: { x: node.position_x, y: node.position_y },
    draggable: !(node.locked ?? false),
    ...flowNodeDimensionsFromRaw(node),
    data: {
      type: node.type,
      label: node.title,
      content: node.content,
      extra_data: node.extra_data,
      layer: node.layer ?? 0,
      scope: node.scope ?? "local",
      locked: node.locked ?? false,
    },
  }));
}

export function buildFlowCharacterRelations(relationsData) {
  return (relationsData.relations || []).map((relation) => ({
    id: relation.id,
    source: relation.source_id,
    target: relation.target_id,
    type: "characterRelation",
    label: relation.relation_type,
    markerEnd: { type: MarkerType.ArrowClosed },
    data: {
      isCharacterRelation: true,
      relation_type: relation.relation_type,
      label: relation.label || "",
    },
  }));
}

export function buildFlowEdges(edgesData, nodes = []) {
  const nodeTypeById = nodes.length && nodes[0].data
    ? nodeTypeByIdFromFlowNodes(nodes)
    : nodeTypeByIdFromRawNodes(nodes);
  return edgesData.edges.map((edge) => {
    const sourceType = nodeTypeById.get(edge.source_id);
    return {
      id: edge.id,
      source: edge.source_id,
      target: edge.target_id,
      type: "custom",
      animated: edge.edge_type === "hints",
      label: edge.label,
      style: getStructuralEdgeStyle(edge.edge_type, sourceType),
      markerEnd: { type: MarkerType.ArrowClosed },
      data: { edge_type: edge.edge_type, extra_data: edge.extra_data || {} },
    };
  });
}

export function toCanvasSnapshot(nodes, edges, characterRelations = []) {
  return {
    nodes: nodes.map((node) => ({
      id: node.id,
      type: node.data.type,
      title: node.data.label,
      content: node.data.content || "",
      extra_data: node.data.extra_data || {},
      layer: node.data.layer ?? 0,
      scope: node.data.scope ?? "local",
      position_x: node.position.x,
      position_y: node.position.y,
    })),
    edges: edges.map((edge) => ({
      id: edge.id,
      source_id: edge.source,
      target_id: edge.target,
      edge_type: edge.data?.edge_type || "uses",
      label: edge.label || "",
      extra_data: edge.data?.extra_data || {},
    })),
    character_relations: characterRelations.map((relation) => ({
      id: relation.id,
      source_id: relation.source,
      target_id: relation.target,
      relation_type: relation.data?.relation_type || relation.label || "关系",
      label: relation.data?.label || "",
    })),
  };
}

export function canvasSnapshotKey(snapshot) {
  return JSON.stringify(snapshot);
}
