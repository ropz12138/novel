import { describe, expect, it } from "vitest";
import { getLatestSupervisorSession } from "./supervisorSession";

describe("getLatestSupervisorSession", () => {
  it("returns null for empty list", () => {
    expect(getLatestSupervisorSession([])).toBeNull();
    expect(getLatestSupervisorSession(null)).toBeNull();
  });

  it("returns first session as latest", () => {
    const sessions = [
      { id: "s-new", updated_at: "2026-06-06T22:00:00Z" },
      { id: "s-old", updated_at: "2026-06-05T10:00:00Z" },
    ];
    expect(getLatestSupervisorSession(sessions)?.id).toBe("s-new");
  });
});
