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

  getSupervisorMessages(sessionId, { beforeSortOrder } = {}) {
    const body = { session_id: sessionId };
    if (beforeSortOrder != null) body.before_sort_order = beforeSortOrder;
    return postRpc("/supervisor-sessions/messages", body);
  },

  getSupervisorDiffDetail(sessionId, messageId) {
    return postRpc("/supervisor-sessions/messages/diff", {
      session_id: sessionId,
      message_id: messageId,
    });
  },

  stopSupervisor(sessionId) {
    return postRpc("/supervisor/stop", { session_id: sessionId });
  },

  getSupervisor(sessionId) {
    return postRpc("/supervisor-sessions/get", { session_id: sessionId });
  },

  deleteSupervisor(sessionId) {
    return postRpc("/supervisor-sessions/delete", { session_id: sessionId });
  },
};
