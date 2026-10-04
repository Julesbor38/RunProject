import { defineConfig } from "vite";

export default defineConfig({
  // MapLibre 6 loads its worker from a sibling file (maplibre-gl-worker.mjs) that the dep optimizer doesn't copy.
  optimizeDeps: { exclude: ["maplibre-gl"] },
  server: {
    host: true, // reachable from Windows when WSL localhost forwarding is off
    proxy: { "/api": "http://localhost:8000" },
  },
});
