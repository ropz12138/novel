import { authFetch, parseResponse } from "./authFetch";
import { API_BASE } from "./runtime-config";

export const researchApi = {
  uploadWork(file) {
    return authFetch(`${API_BASE}/research/works?filename=${encodeURIComponent(file.name)}`, {
      method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file,
    }).then(parseResponse);
  },
  listWorks() {
    return authFetch(`${API_BASE}/research/works`).then(parseResponse);
  },
  listArtifacts(workId) {
    return authFetch(`${API_BASE}/research/works/${workId}/artifacts`).then(parseResponse);
  },
  getLibrary() {
    return authFetch(`${API_BASE}/research/library`).then(parseResponse);
  },
  listVersions(workId) {
    return authFetch(`${API_BASE}/research/works/${workId}/versions`).then(parseResponse);
  },
  downloadUrl(workId, versionId) {
    return `${API_BASE}/research/works/${workId}/versions/${versionId}/download`;
  },
  listSessions() {
    return authFetch(`${API_BASE}/research/sessions`).then(parseResponse);
  },
  createSession(title = "新对话") {
    return authFetch(`${API_BASE}/research/sessions`, {
      method: "POST", body: JSON.stringify({ title }),
    }).then(parseResponse);
  },
  getSession(sessionId) {
    return authFetch(`${API_BASE}/research/sessions/${sessionId}`).then(parseResponse);
  },
  sendMessage(sessionId, message, workId = null, chapterReference = null) {
    return authFetch(`${API_BASE}/research/sessions/${sessionId}/messages`, {
      method: "POST", body: JSON.stringify({
        message,
        work_id: workId,
        chapter_version_id: chapterReference?.versionId ?? null,
        chapter_index: chapterReference?.sectionIndex ?? null,
      }),
    }).then(parseResponse);
  },
  listChapters(workId, versionId) {
    return authFetch(`${API_BASE}/research/works/${workId}/versions/${versionId}/chapters`).then(parseResponse);
  },
  getChapter(workId, versionId, sectionIndex) {
    return authFetch(`${API_BASE}/research/works/${workId}/versions/${versionId}/chapters/${sectionIndex}`).then(parseResponse);
  },
};
