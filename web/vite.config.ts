import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies /api to the atlas_web adapter, which binds to loopback
// and sets the opaque atlas_session cookie. Proxying (rather than pointing the
// browser straight at :8000) keeps the API same-origin in development, so
// `credentials: "include"` needs no CORS exception and the cookie stays Strict.
const API_TARGET = process.env.ATLAS_WEB_API_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // Pinned, not merely preferred. Without strictPort Vite silently walks to
    // 5176 when 5175 is taken, which moves the console out from under anything
    // bookmarked, scripted, or proxied. Failing is the honest answer: the
    // operator sees which port is busy and frees it.
    port: 5175,
    strictPort: true,
    proxy: { "/api": { target: API_TARGET, changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
