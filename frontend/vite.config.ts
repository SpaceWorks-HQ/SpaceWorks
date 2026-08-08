import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// This config file runs in Node, but the project carries no @types/node (the app
// itself is browser-only). Declaring the one global we need keeps `tsc -b` happy
// without pulling in a dependency the app never uses.
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5000,
    // Inside the dev container the backend is another service on the compose
    // network, not localhost — docker-compose.dev.yml sets this to http://backend:8000.
    proxy: {
      "/api": {
        target: process.env.VITE_DEV_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
