import { API_BASE } from "./runtime-config";

/**
 * Drop-in replacement for fetch() that automatically injects the JWT
 * Authorization header from localStorage and handles 401 responses.
 *
 * Usage: identical to fetch(url, options) — just import and call authFetch.
 */
export function authFetch(url, options = {}) {
  const token = localStorage.getItem("novel_token");

  const headers = new Headers(options.headers || {});
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!headers.has("Content-Type") && options.body && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }

  return fetch(url, { ...options, headers }).then((response) => {
    if (response.status === 401) {
      localStorage.removeItem("novel_token");
      localStorage.removeItem("novel_user");
      window.location.href = "/login";
      return Promise.reject(new Error("Unauthorized"));
    }
    return response;
  });
}

/**
 * Helper: build a full API URL from a relative path.
 */
export function apiUrl(path) {
  return `${API_BASE}${path}`;
}
