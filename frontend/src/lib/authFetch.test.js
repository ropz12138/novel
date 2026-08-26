import { beforeEach, describe, expect, it, vi } from "vitest";
import { authJson, parseResponse, publicJson } from "./authFetch";

describe("API response helpers", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("adds the bearer token and JSON content type", async () => {
    localStorage.setItem("novel_token", "token-1");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ id: "ok" }),
    });

    await expect(authJson("/api/example", {
      method: "POST",
      body: JSON.stringify({ title: "测试" }),
    })).resolves.toEqual({ id: "ok" });

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.get("Authorization")).toBe("Bearer token-1");
    expect(options.headers.get("Content-Type")).toBe("application/json");
  });

  it("keeps public requests free of authorization headers", async () => {
    localStorage.setItem("novel_token", "stale-token");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ token: "new-token" }),
    });

    await publicJson("/api/auth/login", {
      method: "POST",
      body: "{}",
    });

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.has("Authorization")).toBe(false);
  });

  it("returns null for an empty successful response", async () => {
    await expect(parseResponse({ ok: true, status: 204 })).resolves.toBeNull();
  });

  it("uses FastAPI validation details in errors", async () => {
    const response = {
      ok: false,
      status: 422,
      json: vi.fn().mockResolvedValue({ detail: [{ msg: "字段不合法" }] }),
    };
    await expect(parseResponse(response, "保存失败")).rejects.toThrow("字段不合法");
  });
});
