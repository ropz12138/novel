import { registerPlugin } from "@capacitor/core";

import { API_BASE, APP_CONFIG } from "./runtime-config";


const ApkUpdate = registerPlugin("ApkUpdate");


export async function getAppRelease(fetchImpl = fetch) {
  const response = await fetchImpl(`${API_BASE}/app/release`);
  if (!response.ok) throw new Error(`检查更新失败 (${response.status})`);
  return response.json();
}


export function resolveAppDownloadUrl(downloadUrl) {
  return new URL(downloadUrl, APP_CONFIG.serverBaseUrl).toString();
}


export async function installAppUpdate(downloadUrl, apkUpdate = ApkUpdate) {
  await apkUpdate.downloadAndInstall({
    url: resolveAppDownloadUrl(downloadUrl),
  });
}
