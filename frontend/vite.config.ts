import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev server proxies the backend so the browser only talks to one origin
// (no CORS setup needed in FastAPI).
export default defineConfig({
  plugins: [react()],
  // MapLibre v6 loads its web worker from a file next to its own module
  // (new URL(..., import.meta.url)). Vite's dependency pre-bundling moves the
  // module and breaks that path, so it is served as-is instead.
  optimizeDeps: { exclude: ["maplibre-gl"] },
  server: {
    proxy: {
      // GET /api/tracks -> http://localhost:8000/tracks
      "/api": {
        target: "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/live": { target: "ws://localhost:8000", ws: true },
    },
  },
  test: { environment: "node" },
});
