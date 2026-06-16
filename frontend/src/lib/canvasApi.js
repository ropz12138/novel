import { API_BASE } from "./runtime-config";

function getAuthHeaders() {
  const token = localStorage.getItem("novel_token");
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

// ========== 作品API ==========

export async function fetchWorks() {
  const res = await fetch(`${API_BASE}/works`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch works");
  return res.json();
}

export async function createWork(data = {}) {
  const res = await fetch(`${API_BASE}/works`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create work");
  return res.json();
}

export async function getWork(workId) {
  const res = await fetch(`${API_BASE}/works/${workId}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch work");
  return res.json();
}

export async function updateWork(workId, data) {
  const res = await fetch(`${API_BASE}/works/${workId}`, {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update work");
  return res.json();
}

export async function deleteWork(workId) {
  const res = await fetch(`${API_BASE}/works/${workId}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete work");
}

// ========== 节点API ==========

export async function fetchNodes(workId) {
  const res = await fetch(`${API_BASE}/works/${workId}/nodes`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch nodes");
  return res.json();
}

export async function createNode(workId, data) {
  const res = await fetch(`${API_BASE}/works/${workId}/nodes`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create node");
  return res.json();
}

export async function updateNode(id, data) {
  const res = await fetch(`${API_BASE}/nodes/${id}`, {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update node");
  return res.json();
}

export async function deleteNode(id) {
  const res = await fetch(`${API_BASE}/nodes/${id}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete node");
}

// ========== 连线API ==========

export async function fetchEdges(workId) {
  const res = await fetch(`${API_BASE}/works/${workId}/edges`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch edges");
  return res.json();
}

export async function createEdge(workId, data) {
  const res = await fetch(`${API_BASE}/works/${workId}/edges`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create edge");
  return res.json();
}

export async function updateEdge(id, data) {
  const res = await fetch(`${API_BASE}/edges/${id}`, {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update edge");
  return res.json();
}

export async function deleteEdge(id) {
  const res = await fetch(`${API_BASE}/edges/${id}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete edge");
}

// ========== 章节生成API ==========

export async function generateChapter(nodeId, extraInstructions = "") {
  const res = await fetch(`${API_BASE}/generate`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({
      node_id: nodeId,
      extra_instructions: extraInstructions,
    }),
  });
  if (!res.ok) throw new Error("Failed to generate chapter");
  return res.json();
}

export async function fetchChapter(nodeId) {
  const res = await fetch(`${API_BASE}/chapters/${nodeId}`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch chapter");
  return res.json();
}
