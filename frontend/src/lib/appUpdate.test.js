import { describe, expect, it, vi } from "vitest";

import { compareVersions, getAppRelease, installAppUpdate } from "./appUpdate";


describe("compareVersions", () => {
  it("compares each numeric version segment", () => {
    expect(compareVersions("1.10.0", "1.9.9")).toBeGreaterThan(0);
    expect(compareVersions("1.0", "1.0.0")).toBe(0);
    expect(compareVersions("2.0.0", "2.0.1")).toBeLessThan(0);
  });
});


describe("getAppRelease", () => {
  it("requests the public release endpoint", async () => {
    const fetchImpl = async (url) => ({
      ok: true,
      json: async () => ({ version_name: "1.1.0", download_url: "/novel/novel.apk" }),
      requestedUrl: url,
    });

    const release = await getAppRelease(fetchImpl);

    expect(release.version_name).toBe("1.1.0");
    expect(release.download_url).toBe("/novel/novel.apk");
  });
});


describe("installAppUpdate", () => {
  it("downloads and installs the APK in-app", async () => {
    const apkUpdate = {
      downloadAndInstall: vi.fn().mockResolvedValue(undefined),
    };

    await installAppUpdate("/novel/novel.apk", apkUpdate);

    expect(apkUpdate.downloadAndInstall).toHaveBeenCalledWith({
      url: "https://liyicheng12138.cn/novel/novel.apk",
    });
  });
});



describe("compareVersions", () => {
  it("compares each numeric version segment", () => {
    expect(compareVersions("1.10.0", "1.9.9")).toBeGreaterThan(0);
    expect(compareVersions("1.0", "1.0.0")).toBe(0);
    expect(compareVersions("2.0.0", "2.0.1")).toBeLessThan(0);
  });
});


describe("getAppRelease", () => {
  it("requests the public release endpoint", async () => {
    const fetchImpl = async (url) => ({
      ok: true,
      json: async () => ({ version_name: "1.1.0", download_url: "/novel/novel.apk" }),
      requestedUrl: url,
    });

    const release = await getAppRelease(fetchImpl);

    expect(release.version_name).toBe("1.1.0");
    expect(release.download_url).toBe("/novel/novel.apk");
  });
});
