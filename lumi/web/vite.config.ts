import fs from "fs";
import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const versionFile = path.resolve(__dirname, "../VERSION_WEB");
const webVersion = fs.existsSync(versionFile)
  ? fs.readFileSync(versionFile, "utf-8").trim()
  : "dev";

// https://vite.dev/config/
export default defineConfig({
  define: {
    __WEB_VERSION__: JSON.stringify(webVersion),
  },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://<DEVICE_IP>",
        changeOrigin: true,
      },
      "/hw": {
        target: "http://<DEVICE_IP>",
        changeOrigin: true,
      },
    },
  },
});
