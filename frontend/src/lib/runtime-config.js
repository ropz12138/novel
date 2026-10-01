import { Capacitor } from "@capacitor/core";

const DEV_API_BASE = "http://127.0.0.1:9001/api";
const PROD_API_BASE = "/novel/api";

export const APP_CONFIG = __NOVEL_APP_CONFIG__;
export const IS_NATIVE_APP = Capacitor.isNativePlatform();
export const API_BASE = IS_NATIVE_APP
  ? APP_CONFIG.apiBaseUrl
  : (import.meta.env.PROD ? PROD_API_BASE : DEV_API_BASE);
