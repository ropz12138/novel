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
      const base = import.meta.env.BASE_URL || "/";
      window.location.assign(`${base.replace(/\/?$/, "/")}login`);
      return Promise.reject(new Error("Unauthorized"));
    }
    return response;
  });
}

export async function parseResponse(response, fallbackMessage = "请求失败") {
  if (response.ok) {
    if (response.status === 204) return null;
    try {
      return await response.json();
    } catch {
      return null;
    }
  }

  let message = `${fallbackMessage} (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string" && body.detail) {
      message = body.detail;
    } else if (Array.isArray(body.detail) && body.detail[0]?.msg) {
      message = body.detail[0].msg;
    } else {
      message = body.message || message;
    }
  } catch {
    // The status code still gives the caller a useful failure reason.
  }
  throw new Error(message);
}

export function authJson(url, options = {}, fallbackMessage) {
  return authFetch(url, options).then((response) =>
    parseResponse(response, fallbackMessage),
  );
}

export function publicJson(url, options = {}, fallbackMessage) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Content-Type") && options.body && typeof options.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  return fetch(url, { ...options, headers }).then((response) =>
    parseResponse(response, fallbackMessage),
  );
}
