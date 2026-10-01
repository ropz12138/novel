import { authFetch, parseResponse } from "./authFetch";
import { API_BASE } from "./runtime-config";

export const tokenUsageApi = {
  getUsage(workId, grain = "day") {
    const params = new URLSearchParams();
    if (workId) params.set("work_id", workId);
    params.set("grain", grain);
    return authFetch(`${API_BASE}/token-usage?${params}`).then((response) => parseResponse(response, "加载 Token 用量失败"));
  },
};
