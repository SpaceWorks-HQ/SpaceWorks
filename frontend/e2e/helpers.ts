import { readFileSync } from "node:fs";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

declare const process: { env: Record<string, string | undefined> };

// The seed command (backend/apps/operations/management/commands/seed_e2e.py) creates a FRESH
// makerspace per run and writes its identifiers to e2e/.seed.json (scripts/e2e-local.sh passes
// --write-json). The constants below are the fallbacks and the fixed strings the seed uses.
export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8100";

type SeedFile = {
  slug: string;
  makerspace_id: number;
  makerspace_name: string;
  manager: { username: string; password: string };
  member: { username: string; password: string };
  box_code: string;
  box_label: string;
  product: string;
  secret_location: string;
  pending_request_for: string;
  probe_request_for: string;
};

function loadSeed(): SeedFile | null {
  const candidate = process.env.E2E_SEED_FILE ?? new URL("./.seed.json", import.meta.url).pathname;
  try {
    return JSON.parse(readFileSync(candidate, "utf8")) as SeedFile;
  } catch {
    return null;
  }
}

const seedFile = loadSeed();

export const SEED = {
  slug: seedFile?.slug ?? "e2e-space",
  makerspaceId: seedFile?.makerspace_id ?? 0,
  makerspaceName: seedFile?.makerspace_name ?? "E2E Makerspace",
  manager: seedFile?.manager ?? { username: "e2e_manager", password: process.env.E2E_PASSWORD ?? "e2e-pass-12345" },
  member: seedFile?.member ?? { username: "e2e_member", password: process.env.E2E_PASSWORD ?? "e2e-pass-12345" },
  boxCode: seedFile?.box_code ?? "e2e-box-0001",
  boxLabel: seedFile?.box_label ?? "E2E Shelf A",
  product: seedFile?.product ?? "E2E Cordless Drill",
  secretLocation: seedFile?.secret_location ?? "E2E SECRET SHELF 42",
  pendingRequestFor: seedFile?.pending_request_for ?? "E2E robotics workshop",
  probeRequestFor: seedFile?.probe_request_for ?? "E2E hard-rules probe",
};

export async function apiLogin(request: APIRequestContext, username: string, password: string): Promise<string> {
  const response = await request.post(`${API_URL}/api/v1/auth/login`, { data: { username, password } });
  expect(response.ok(), `login failed: ${response.status()} ${await response.text()}`).toBeTruthy();
  const body = (await response.json()) as { access: string };
  return body.access;
}

export async function apiGet<T>(request: APIRequestContext, token: string, path: string): Promise<T> {
  const response = await request.get(`${API_URL}/api/v1${path}`, { headers: { Authorization: `Bearer ${token}` } });
  expect(response.ok(), `${path} -> ${response.status()} ${await response.text()}`).toBeTruthy();
  return (await response.json()) as T;
}

export async function apiPost(request: APIRequestContext, token: string, path: string, data: unknown) {
  return request.post(`${API_URL}/api/v1${path}`, { headers: { Authorization: `Bearer ${token}` }, data });
}

export async function makerspaceId(request: APIRequestContext, token: string): Promise<number> {
  if (SEED.makerspaceId) return SEED.makerspaceId;
  const spaces = await apiGet<Array<{ id: number; slug: string }> | { results: Array<{ id: number; slug: string }> }>(
    request, token, "/admin/makerspaces",
  );
  const rows = Array.isArray(spaces) ? spaces : spaces.results;
  const space = rows.find((row) => row.slug === SEED.slug);
  expect(space, "seeded makerspace missing; run `manage.py seed_e2e --reset`").toBeTruthy();
  return space!.id;
}

export async function staffLogin(page: Page, username = SEED.manager.username, password = SEED.manager.password) {
  await page.goto(`/m/${SEED.slug}/admin`);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: /sign in|log in/i }).click();
  // Login lands on the dashboard; wait for that navigation before doing anything else, or a
  // goto() races the post-login redirect and the refresh cookie.
  await page.waitForURL(/\/admin(\/|$)/);
  await expect(page.getByRole("button", { name: /sign in|log in/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /sign out/i })).toBeVisible();
}

export async function openRequestsTab(page: Page) {
  await page.goto(`/m/${SEED.slug}/admin/requests`);
  await expect(page.getByText("Pending review")).toBeVisible({ timeout: 15_000 });
}

export const EVIDENCE_FIXTURE = new URL("./fixtures/evidence.jpg", import.meta.url).pathname;
