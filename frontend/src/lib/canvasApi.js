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

export async function restoreCanvasSnapshot(workId, snapshot) {
  const res = await fetch(`${API_BASE}/works/${workId}/canvas/restore`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(snapshot),
  });
  if (!res.ok) throw new Error("Failed to restore canvas snapshot");
  return res.json();
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

// ========== 角色关系线 API ==========

export async function fetchCharacterRelations(workId) {
  const res = await fetch(`${API_BASE}/works/${workId}/character-relations`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch character relations");
  return res.json();
}

export async function createCharacterRelation(workId, data) {
  const res = await fetch(`${API_BASE}/works/${workId}/character-relations`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create character relation");
  return res.json();
}

export async function updateCharacterRelation(id, data) {
  const res = await fetch(`${API_BASE}/character-relations/${id}`, {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update character relation");
  return res.json();
}

export async function deleteCharacterRelation(id) {
  const res = await fetch(`${API_BASE}/character-relations/${id}`, {
    method: "DELETE",
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to delete character relation");
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

// ========== 模型配置API ==========

export async function getModels() {
  const res = await fetch(`${API_BASE}/me/models`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch models");
  return res.json();
}

export async function getModelPref() {
  const res = await fetch(`${API_BASE}/me/model-pref`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch model preference");
  return res.json();
}

export async function putModelPref(data) {
  const res = await fetch(`${API_BASE}/me/model-pref`, {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update model preference");
  return res.json();
}

// ========== 画布截图上传（供多模态评估） ==========

export async function uploadCanvasRender(workId, base64Image) {
  const res = await fetch(`${API_BASE}/works/${workId}/canvas/render`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ image: base64Image }),
  });
  if (!res.ok) throw new Error("Failed to upload canvas render");
  return res.json();
}
