import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8020",
      "/health": "http://127.0.0.1:8020",
      "/ready": "http://127.0.0.1:8020",
      "/ask": "http://127.0.0.1:8020",
      "/usage": "http://127.0.0.1:8020",
    },
  },
});
