import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/novel/",
  plugins: [react()],
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
    setupFiles: ["src/test/setupCodemirrorMock.js"],
  },
});
