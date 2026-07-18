import { authFetch } from "./authFetch";
import { API_BASE } from "./runtime-config";

function postRpc(path, body = {}) {
  return authFetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** API helpers for supervisor session management. */
export const sessionApi = {
  listSupervisor(workId) {
    return postRpc("/supervisor-sessions/list", workId ? { work_id: workId } : {}).then((r) => {
      if (!r.ok) throw new Error("Failed to load supervisor sessions");
      return r.json();
    });
  },

  getSupervisorMessages(sessionId) {
    return postRpc("/supervisor-sessions/messages", { session_id: sessionId }).then((r) => {
      if (!r.ok) throw new Error("Failed to load supervisor messages");
      return r.json();
    });
  },

  deleteSupervisor(sessionId) {
    return postRpc("/supervisor-sessions/delete", { session_id: sessionId }).then((r) => {
      if (!r.ok) throw new Error("Failed to delete supervisor session");
      return r.json().catch(() => ({}));
    });
  },
};
