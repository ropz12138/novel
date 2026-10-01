import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectConfig = JSON.parse(fs.readFileSync(path.join(projectRoot, "config.json"), "utf8"));
const mobileConfig = projectConfig.app.mobile;

export default defineConfig({
  base: process.env.NOVEL_APP_BUILD === "1" ? "./" : "/novel/",
  plugins: [react()],
  define: {
    __NOVEL_APP_CONFIG__: JSON.stringify({
      versionName: mobileConfig.version_name,
      versionCode: mobileConfig.version_code,
      serverBaseUrl: mobileConfig.server_base_url,
      apiBaseUrl: mobileConfig.api_base_url,
      downloadUrl: mobileConfig.download_url,
    }),
  },
  server: {
    allowedHosts: ["liyicheng12138.cn", "www.liyicheng12138.cn"],
    proxy: {
      "/novel/api": {
        target: "http://127.0.0.1:9001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/novel\/api/, "/api"),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{js,jsx}"],
  },
});
