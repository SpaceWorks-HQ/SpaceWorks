import { defineConfig, devices } from "@playwright/test";

// End-to-end suite. It drives a REAL stack (Django + Postgres + MinIO + the frontend), never
// mocks: the point is to pin the Hard Rules where they are enforced. Point it at a running
// stack with E2E_BASE_URL / E2E_API_URL; `manage.py seed_e2e --reset` must have run first.
// Locally: scripts/e2e-local.sh; in CI: the `e2e` job in .github/workflows/tests.yml.
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["html", { open: "never" }], ["list"]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5100",
    trace: "retain-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
