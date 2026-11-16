import { describe, expect, it, vi } from "vitest";

import { getAppRelease, installAppUpdate } from "./appUpdate";


describe("getAppRelease", () => {
  it("requests the public release endpoint", async () => {
    const fetchImpl = async () => ({
      ok: true,
      json: async () => ({ version_name: "1.1.0", download_url: "/novel/novel.apk" }),
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
