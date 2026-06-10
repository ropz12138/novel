import { authFetch } from "./authFetch";
import { API_BASE } from "./runtime-config";

/** 统一 POST RPC 调用（方案 A：动作路径 + JSON body） */
export function postRpc(path, body = {}) {
  return authFetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export const workApi = {
  list() {
    return postRpc("/works/list");
  },
  get(workId) {
    return postRpc("/works/get", { work_id: workId });
  },
  delete(workId) {
    return postRpc("/works/delete", { work_id: workId });
  },
  updateOutline(workId, outlineTree) {
    return postRpc("/works/update-outline", { work_id: workId, outline_tree: outlineTree });
  },
  listChapters(workId) {
    return postRpc("/works/chapters/list", { work_id: workId });
  },
  getChapterIntel(workId, chapterNumber) {
    return postRpc("/works/chapters/intel", { work_id: workId, chapter_number: chapterNumber });
  },
  updateChapter(workId, chapterNumber, data) {
    return postRpc("/works/chapters/update", {
      work_id: workId,
      chapter_number: chapterNumber,
      ...data,
    });
  },
  deleteLastChapter(workId) {
    return postRpc("/works/chapters/delete-last", { work_id: workId });
  },
  getRequirementsDoc(workId) {
    return postRpc("/works/requirements-doc/get", { work_id: workId });
  },
  updateRequirementsDoc(workId, content) {
    return postRpc("/works/requirements-doc/update", { work_id: workId, content });
  },
  getMesoDoc(workId) {
    return postRpc("/works/meso-doc/get", { work_id: workId });
  },
  updateMesoDoc(workId, content) {
    return postRpc("/works/meso-doc/update", { work_id: workId, content });
  },
  getMicroDoc(workId) {
    return postRpc("/works/micro-doc/get", { work_id: workId });
  },
  updateMicroDoc(workId, content) {
    return postRpc("/works/micro-doc/update", { work_id: workId, content });
  },
};

export const characterApi = {
  list(workId) {
    return postRpc("/works/characters/list", { work_id: workId });
  },
  create(workId, data) {
    return postRpc("/works/characters/create", { work_id: workId, ...data });
  },
  update(workId, characterId, data) {
    return postRpc("/works/characters/update", {
      work_id: workId,
      character_id: characterId,
      ...data,
    });
  },
  delete(workId, characterId) {
    return postRpc("/works/characters/delete", {
      work_id: workId,
      character_id: characterId,
    });
  },
};
