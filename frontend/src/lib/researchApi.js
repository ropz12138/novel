import { authFetch, parseResponse } from "./authFetch";
import { API_BASE } from "./runtime-config";

export const researchApi = {
  upload(file) {
    return authFetch(
      `${API_BASE}/research/jobs?filename=${encodeURIComponent(file.name)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: file,
      },
    ).then(parseResponse);
  },

  listJobs() {
    return authFetch(`${API_BASE}/research/jobs`).then(parseResponse);
  },

  getJob(jobId) {
    return authFetch(`${API_BASE}/research/jobs/${jobId}`).then(parseResponse);
  },

  getEvents(jobId, after = 0) {
    return authFetch(
      `${API_BASE}/research/jobs/${jobId}/events?after=${after}&limit=500`,
    ).then(parseResponse);
  },

  pause(jobId) {
    return authFetch(`${API_BASE}/research/jobs/${jobId}/pause`, {
      method: "POST",
    }).then(parseResponse);
  },

  continue(jobId, message) {
    return authFetch(`${API_BASE}/research/jobs/${jobId}/continue`, {
      method: "POST",
      body: JSON.stringify({ message }),
    }).then(parseResponse);
  },

  downloadUrl(jobId, versionId) {
    return `${API_BASE}/research/jobs/${jobId}/versions/${versionId}/download`;
  },
};
