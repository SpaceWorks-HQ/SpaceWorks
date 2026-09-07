import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Playwright owns e2e/*.spec.ts (playwright.config.ts); vitest runs only the unit tests.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
