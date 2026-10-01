import { registerPlugin } from "@capacitor/core";

import { API_BASE, APP_CONFIG } from "./runtime-config";


const ApkUpdate = registerPlugin("ApkUpdate");


export function compareVersions(left, right) {
  const leftParts = String(left).split(".").map(Number);
  const rightParts = String(right).split(".").map(Number);
  const length = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < length; index += 1) {
    const difference = (leftParts[index] || 0) - (rightParts[index] || 0);
    if (difference !== 0) return difference;
  }
  return 0;
}


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
