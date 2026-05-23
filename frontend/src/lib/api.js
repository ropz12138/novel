import { authFetch } from "./authFetch";
import { API_BASE } from "./runtime-config";
/** API helpers for supervisor session management. */

export const sessionApi = {
  // ── Supervisor sessions ──

  listSupervisor(workId) {
    const params = workId ? `?work_id=${workId}` : "";
    return authFetch(`${API_BASE}/supervisor-sessions${params}`).then((r) => {
      if (!r.ok) throw new Error("Failed to load supervisor sessions");
      return r.json();
    });
  },

  getSupervisorMessages(sessionId) {
    return authFetch(
      `${API_BASE}/supervisor-sessions/${sessionId}/messages`
    ).then((r) => {
      if (!r.ok) throw new Error("Failed to load supervisor messages");
      return r.json();
    });
  },

  deleteSupervisor(sessionId) {
    return authFetch(`${API_BASE}/supervisor-sessions/${sessionId}`, {
      method: "DELETE",
    }).then((r) => {
      if (!r.ok && r.status !== 204) throw new Error("Failed to delete supervisor session");
    });
  },
};
