import { API_BASE } from "./runtime-config";
import { authJson } from "./authFetch";

// ========== 作品API ==========

export async function fetchWorks() {
  return authJson(`${API_BASE}/works`, {}, "加载作品失败");
}

export async function createWork(data = {}) {
  return authJson(`${API_BASE}/works`, {
    method: "POST",
    body: JSON.stringify(data),
  }, "创建作品失败");
}

export async function deleteWork(workId) {
  return authJson(`${API_BASE}/works/${workId}`, {
    method: "DELETE",
  }, "删除作品失败");
}

export async function restoreCanvasSnapshot(workId, snapshot) {
  return authJson(`${API_BASE}/works/${workId}/canvas/restore`, {
    method: "POST",
    body: JSON.stringify(snapshot),
  }, "恢复画布失败");
}

// ========== 节点API ==========

export async function fetchNodes(workId) {
  return authJson(`${API_BASE}/works/${workId}/nodes`, {}, "加载节点失败");
}

export async function createNode(workId, data) {
  return authJson(`${API_BASE}/works/${workId}/nodes`, {
    method: "POST",
    body: JSON.stringify(data),
  }, "创建节点失败");
}

export async function updateNode(id, data) {
  return authJson(`${API_BASE}/nodes/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  }, "更新节点失败");
}

export async function deleteNode(id) {
  return authJson(`${API_BASE}/nodes/${id}`, {
    method: "DELETE",
  }, "删除节点失败");
}

// ========== 连线API ==========

export async function fetchEdges(workId) {
  return authJson(`${API_BASE}/works/${workId}/edges`, {}, "加载连线失败");
}

export async function createEdge(workId, data) {
  return authJson(`${API_BASE}/works/${workId}/edges`, {
    method: "POST",
    body: JSON.stringify(data),
  }, "创建连线失败");
}

export async function updateEdge(id, data) {
  return authJson(`${API_BASE}/edges/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  }, "更新连线失败");
}

export async function deleteEdge(id) {
  return authJson(`${API_BASE}/edges/${id}`, {
    method: "DELETE",
  }, "删除连线失败");
}

// ========== 角色关系线 API ==========

export async function fetchCharacterRelations(workId) {
  return authJson(`${API_BASE}/works/${workId}/character-relations`, {}, "加载角色关系失败");
}

export async function createCharacterRelation(workId, data) {
  return authJson(`${API_BASE}/works/${workId}/character-relations`, {
    method: "POST",
    body: JSON.stringify(data),
  }, "创建角色关系失败");
}

export async function deleteCharacterRelation(id) {
  return authJson(`${API_BASE}/character-relations/${id}`, {
    method: "DELETE",
  }, "删除角色关系失败");
}

// ========== 模型配置API ==========

export async function getModels() {
  return authJson(`${API_BASE}/me/models`, {}, "加载模型列表失败");
}

export async function getModelPref() {
  return authJson(`${API_BASE}/me/model-pref`, {}, "加载模型偏好失败");
}

export async function putModelPref(data) {
  return authJson(`${API_BASE}/me/model-pref`, {
    method: "PUT",
    body: JSON.stringify(data),
  }, "更新模型偏好失败");
}
