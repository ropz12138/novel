import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AppUpdateButton from "./AppUpdateButton";


describe("AppUpdateButton", () => {
  it("installs the APK in-app when a newer version exists", async () => {
    const installUpdate = vi.fn().mockResolvedValue(undefined);
    const fetchRelease = vi.fn().mockResolvedValue({
      version_name: "1.1.0",
      version_code: 2,
      download_url: "/novel/novel.apk",
    });

    render(
      <AppUpdateButton
        currentVersion="1.0.0"
        currentVersionCode={1}
        fetchRelease={fetchRelease}
        installUpdate={installUpdate}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "检查更新" }));

    expect(await screen.findByText("发现新版本 1.1.0")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "下载更新" }));
    expect(await screen.findByText("正在下载并安装…")).toBeDefined();
    await waitFor(() => {
      expect(installUpdate).toHaveBeenCalledWith("/novel/novel.apk");
    });
  });

  it("reports that the current version is latest", async () => {
    const fetchRelease = vi.fn().mockResolvedValue({
      version_name: "1.0.0",
      version_code: 1,
      download_url: "/novel/novel.apk",
    });

    render(
      <AppUpdateButton
        currentVersion="1.0.0"
        currentVersionCode={1}
        fetchRelease={fetchRelease}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "检查更新" }));

    await waitFor(() => {
      expect(screen.getByText("已是最新版本 1.0.0")).toBeDefined();
    });
  });
});
