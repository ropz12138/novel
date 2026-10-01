import { useState } from "react";
import { Download, RefreshCw, X } from "lucide-react";

import { getAppRelease, installAppUpdate } from "../lib/appUpdate";
import { APP_CONFIG } from "../lib/runtime-config";


export default function AppUpdateButton({
  currentVersion = APP_CONFIG.versionName,
  currentVersionCode = APP_CONFIG.versionCode,
  fetchRelease = getAppRelease,
  installUpdate = installAppUpdate,
  buttonClassName,
}) {
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [result, setResult] = useState(null);

  const checkUpdate = async () => {
    setChecking(true);
    try {
      const release = await fetchRelease();
      setResult({
        release,
        hasUpdate: release.version_code > currentVersionCode,
      });
    } catch (error) {
      setResult({ error: error?.message || "检查更新失败" });
    } finally {
      setChecking(false);
    }
  };

  const startInstall = async () => {
    setInstalling(true);
    try {
      await installUpdate(result.release.download_url);
    } catch (error) {
      setResult({ error: error?.message || "下载安装失败" });
    } finally {
      setInstalling(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={checkUpdate}
        disabled={checking}
        className={buttonClassName || "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-slate-600 transition-colors hover:bg-slate-100 disabled:opacity-60"}
        aria-label="检查更新"
        title={`当前版本 ${currentVersion}`}
      >
        <RefreshCw className={`h-4 w-4 ${checking ? "animate-spin" : ""}`} />
        <span>检查更新</span>
      </button>

      {result && (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-slate-950/35 p-4">
          <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="font-semibold text-slate-800">应用更新</h2>
                <p className="mt-2 text-sm text-slate-600">
                  {result.error
                    || (result.hasUpdate
                      ? `发现新版本 ${result.release.version_name}`
                      : `已是最新版本 ${currentVersion}`)}
                </p>
              </div>
              <button type="button" onClick={() => setResult(null)} aria-label="关闭更新提示" disabled={installing}>
                <X className="h-5 w-5 text-slate-400" />
              </button>
            </div>
            {result.hasUpdate && !result.error && (
              <button
                type="button"
                onClick={startInstall}
                disabled={installing}
                className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
              >
                <Download className={`h-4 w-4 ${installing ? "animate-pulse" : ""}`} />
                {installing ? "正在下载并安装…" : "下载更新"}
              </button>
            )}
          </div>
        </div>
      )}
    </>
  );
}
