import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/novel/",
  plugins: [react()],
  server: {
    allowedHosts: ["liyicheng12138.cn", "www.liyicheng12138.cn"],
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{js,jsx}"],
  },
});
