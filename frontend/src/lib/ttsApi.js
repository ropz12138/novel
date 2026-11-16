import { API_BASE } from "./runtime-config";
import { authJson } from "./authFetch";

export function getTtsSettings() {
  return authJson(`${API_BASE}/tts-settings`, {}, "加载朗读设置失败");
}

export function putTtsSettings(settings) {
  return authJson(`${API_BASE}/tts-settings`, {
    method: "PUT",
    body: JSON.stringify(settings),
  }, "保存朗读设置失败");
}
