import { defineConfig } from "vite";

// The app lives under /app/, which is also the PWA scope (manifest): /dl/ (signed GPX links) stays outside
// it, so the iOS home-screen app opens it in a window over the app instead of in place of the app.
export default defineConfig({
  base: "/app/",
  plugins: [
    {
      name: "root-to-app", // dev: / -> /app/, as the API does in production
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url === "/" || req.url === "/index.html") {
            res.writeHead(307, { Location: "/app/" });
            res.end();
          } else next();
        });
      },
    },
  ],
  // MapLibre 6 loads its worker from a sibling file (maplibre-gl-worker.mjs) that the dep optimizer doesn't copy.
  optimizeDeps: { exclude: ["maplibre-gl"] },
  worker: { format: "es" }, // MapLibre starts its worker as a module worker
  server: {
    host: true, // reachable from Windows when WSL localhost forwarding is off
    allowedHosts: [".ts.net"], // the phone, through `tailscale serve` on the PC (tailnet only)
    proxy: { "/api": "http://localhost:8000", "/dl": "http://localhost:8000" },
  },
});
