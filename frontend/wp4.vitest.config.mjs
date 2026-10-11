import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Sandbox validation keeps all generated caches inside this lane.
export default defineConfig({
  plugins: [react()],
  cacheDir: ".wp4-vite-cache",
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], cache: false },
});
