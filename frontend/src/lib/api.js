import { authJson } from "./authFetch";
import { API_BASE } from "./runtime-config";

function postRpc(path, body = {}) {
  return authJson(`${API_BASE}${path}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** API helpers for supervisor session management. */
export const sessionApi = {
  listSupervisor(workId) {
    return postRpc("/supervisor-sessions/list", workId ? { work_id: workId } : {});
  },

  getSupervisorMessages(sessionId) {
    return postRpc("/supervisor-sessions/messages", { session_id: sessionId });
  },

  deleteSupervisor(sessionId) {
    return postRpc("/supervisor-sessions/delete", { session_id: sessionId });
  },
};
