import { defineConfig } from "vite";

// The app lives under /app/, which is also the PWA scope (manifest): /dl/ (signed GPX links) stays outside
// it, so the iOS home-screen app opens it in a window over the app instead of in place of the app.
// `--mode native` (npm run build:native): the iOS app (Capacitor) serves the build from capacitor://localhost/,
// so at the root, into dist-native/ (dist/ stays the web build that the API serves).
export default defineConfig(({ mode }) => ({
  base: mode === "native" ? "/" : "/app/",
  build: { outDir: mode === "native" ? "dist-native" : "dist" },
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
    // CORS is the API's business (only capacitor://localhost, the native app): Vite must not answer the
    // preflights of /api itself (it did, without the allowed origin), but pass them to the proxy.
    cors: false,
    proxy: { "/api": "http://localhost:8000", "/dl": "http://localhost:8000" },
  },
}));
