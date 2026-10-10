import { expect, test, type Page } from "@playwright/test";
import { EVIDENCE_FIXTURE, SEED, apiGet, apiLogin, apiPost, openRequestsTab, staffLogin } from "./helpers";

type ReplayCall = { url: string; headers: Record<string, string>; body: string };
type QueueRow = { id: number; status: string; issue_evidence_id: number | null };
type ReplayRow = { id: string; subject_request_id: number; evidence_id: number; failure_code: string; resolution_code: string | null };
type AuditRow = { actor: number; meta: Record<string, unknown>; target_id: string };
type Timeline = { events: Array<{ kind: string; evidence_id: number | null }> };

async function loadStation(page: Page, requestId: number) {
  const kiosk = SEED.kiosk!;
  await page.goto(`/m/${SEED.slug}/kiosk/${kiosk.station_token}`);
  await page.getByLabel("Station PIN").fill(kiosk.station_pin);
  await page.getByRole("button", { name: "Unlock station" }).click();
  await page.getByRole("button", { name: "Start operator shift" }).click();
  await page.getByLabel("Request number").fill(String(requestId));
  await page.getByRole("button", { name: "Load request" }).click();
  await expect(page.getByRole("region", { name: `Request #${requestId}` })).toBeVisible();
  await page.getByRole("button", { name: "Continue with encrypted queue" }).click();
  await expect(page.getByLabel("Loaded handover")).toBeVisible();
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
}

test("production kiosk survives outage, replays once and resolves revoked-QR evidence", async ({ page, context, request }) => {
  test.setTimeout(180_000);
  expect(SEED.kiosk, "Regenerate the e2e seed with phase 9e fixtures").toBeTruthy();
  const kiosk = SEED.kiosk!;
  const token = await apiLogin(request, SEED.manager.username, SEED.manager.password);
  const me = await apiGet<{ id: number }>(request, token, "/auth/me");
  const executed: ReplayCall[] = [];
  // Capture actual protocol envelopes for duplicate proof. They stay in this test's
  // memory and are never written to seed output or exposed to the UI.
  page.on("request", (req) => {
    if (req.url().includes("/replay/") && req.url().endsWith("/execute/")) {
      executed.push({ url: req.url(), headers: req.headers(), body: req.postData()! });
    }
  });
  await staffLogin(page);
  await loadStation(page, kiosk.success.request_id);
  await context.setOffline(true);
  await page.getByLabel("Operation", { exact: true }).selectOption("assign_box");
  await page.getByLabel("Scan box or return QR").fill(kiosk.success.box_code);
  await page.getByRole("button", { name: "Queue handover" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "Sequence 1" })).toContainText("Queued");
  await page.getByLabel("Operation", { exact: true }).selectOption("reviewed_issue");
  await page.getByLabel("Evidence photo", { exact: true }).setInputFiles(EVIDENCE_FIXTURE);
  await page.getByLabel("Remark", { exact: true }).fill("Offline issue photo");
  await page.getByRole("button", { name: "Queue handover" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "Sequence 2" })).toContainText("Queued");

  // Real IndexedDB contains opaque metadata/ciphertext, not borrower/QR/photo JSON.
  const stored = await page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const opening = indexedDB.open("spaceworks-kiosk-v1");
      opening.onsuccess = () => resolve(opening.result); opening.onerror = () => reject(opening.error);
    });
    const read = (name: string) => new Promise<unknown[]>((resolve) => {
      const value = db.transaction(name).objectStore(name).getAll(); value.onsuccess = () => resolve(value.result);
    });
    try { return JSON.stringify({ records: await read("records"), evidence: await read("evidence") }); }
    finally { db.close(); }
  });
  expect(stored).not.toContain(kiosk.success.box_code);
  expect(stored).not.toContain("Offline issue photo");
  await page.reload();
  await expect(page.getByLabel("Loaded handover")).toBeVisible();
  await expect(page.getByRole("listitem").filter({ hasText: "Sequence 2" })).toContainText("Queued");
  await expect(page.getByLabel("Station PIN")).toHaveCount(0);
  await expect(page.getByLabel("Request number")).toHaveCount(0);
  await expect(page.getByLabel("Scan or type a QR code")).toHaveCount(0);

  await context.setOffline(false);
  await page.getByRole("button", { name: "Retry queued work" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "Sequence 1" })).toContainText("succeeded", { timeout: 30_000 });
  await expect(page.getByRole("listitem").filter({ hasText: "Sequence 2" })).toContainText("succeeded", { timeout: 30_000 });
  const before = await apiGet<Timeline>(request, token, `/admin/requests/${kiosk.success.request_id}/timeline`);
  expect(before.events.filter((event) => event.kind === "box_scan")).toHaveLength(1);
  const active = await apiGet<{ results: QueueRow[] }>(request, token, `/admin/makerspace/${SEED.makerspaceId}/active-loans`);
  const issued = active.results.find((row) => row.id === kiosk.success.request_id)!;
  expect(issued.status).toBe("issued"); expect(issued.issue_evidence_id).toBeTruthy();
  const issueAudit = await apiGet<{ count: number; results: AuditRow[] }>(request, token,
    `/admin/audit-logs?makerspace=${SEED.makerspaceId}&action=request.issued&target_id=${kiosk.success.request_id}`);
  expect(issueAudit.count).toBe(1); expect(issueAudit.results[0].actor).toBe(me.id);
  const channel = await apiGet<{ results: AuditRow[] }>(request, token,
    `/admin/audit-logs?makerspace=${SEED.makerspaceId}&action=kiosk.replay_succeeded`);
  const effects = channel.results.filter((row) => row.meta.result_request_id === kiosk.success.request_id);
  expect(effects).toHaveLength(2);
  for (const row of effects) {
    expect(row.actor).toBe(me.id); expect(row.meta.station_id).toBe(kiosk.station_id);
    expect(row.meta.station_session_id).toBeTruthy(); expect(row.meta.operator_lease_id).toBeTruthy();
  }
  const duplicate = executed.find((call) => JSON.parse(call.body).kind === "reviewed_issue")!;
  expect(duplicate).toBeTruthy();
  const repeated = await page.evaluate(async (call) => {
    const response = await fetch(call.url, { method: "POST", credentials: "include", headers: {
      "Content-Type": "application/json", "X-Station-CSRF": "1", "X-Kiosk-Operator-Lease": call.headers["x-kiosk-operator-lease"],
    }, body: call.body });
    return { status: response.status, body: await response.json() };
  }, duplicate);
  expect(repeated.status).toBe(200); expect(repeated.body.state).toBe("succeeded");
  expect(await apiGet<Timeline>(request, token, `/admin/requests/${kiosk.success.request_id}/timeline`)).toEqual(before);
  await page.getByRole("button", { name: "Acknowledge completion and clear local work" }).click();
  await expect(page.getByLabel("Station PIN")).toBeVisible();

  await loadStation(page, kiosk.revoked.request_id);
  await context.setOffline(true);
  await page.getByLabel("Operation", { exact: true }).selectOption("reviewed_issue");
  await page.getByLabel("Asset QRs (one per line)").fill(kiosk.revoked.qr_payload);
  await page.getByLabel("Evidence photo", { exact: true }).setInputFiles(EVIDENCE_FIXTURE);
  await page.getByRole("button", { name: "Queue handover" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "Sequence 1" })).toContainText("Queued");
  // This API context has its own network, so revocation races a genuinely offline page.
  const revoked = await apiPost(request, token, `/qr/${kiosk.revoked.qr_id}/revoke`, {});
  expect(revoked.status(), await revoked.text()).toBe(200);
  await context.setOffline(false);
  await page.getByRole("button", { name: "Retry queued work" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: "Sequence 1" })).toContainText("qr_revoked", { timeout: 30_000 });
  const failures = await apiGet<{ results: ReplayRow[] }>(request, token, `/admin/makerspace/${SEED.makerspaceId}/kiosk-replays/`);
  const failure = failures.results.find((row) => row.subject_request_id === kiosk.revoked.request_id)!;
  expect(failure.failure_code).toBe("qr_revoked"); expect(failure.evidence_id).toBeTruthy();
  const accepted = await apiGet<{ results: QueueRow[] }>(request, token, `/admin/makerspace/${SEED.makerspaceId}/accepted-requests`);
  expect(accepted.results.find((row) => row.id === kiosk.revoked.request_id)?.status).toBe("accepted");

  await openRequestsTab(page);
  const recovery = page.locator("section").filter({ has: page.getByRole("heading", { name: "Failed kiosk handovers" }) });
  await recovery.getByRole("button", { name: /reviewed issue.*qr_revoked/ }).click();
  await recovery.getByRole("button", { name: "Preview failed evidence" }).click();
  const evidence = recovery.getByRole("link", { name: "Open failed evidence photo" });
  await expect(evidence).toBeVisible();
  const bytes = await request.get((await evidence.getAttribute("href"))!);
  expect(bytes.status()).toBe(200); expect(bytes.headers()["content-type"]).toContain("image/jpeg");
  await recovery.getByRole("button", { name: "Acknowledge — no change occurred" }).click();
  await recovery.getByRole("button", { name: "Confirm acknowledgement" }).click();
  await expect(recovery.getByText("No retained failures in this view.")).toBeVisible();
  await recovery.getByLabel("Recovery status").selectOption("resolved");
  await recovery.getByRole("button", { name: /reviewed issue.*qr_revoked/ }).click();
  await expect(recovery.getByText(/Resolved: acknowledged no change/)).toBeVisible();
  const resolvedAudit = await apiGet<{ results: AuditRow[] }>(request, token,
    `/admin/audit-logs?makerspace=${SEED.makerspaceId}&action=kiosk.replay_resolved`);
  const resolution = resolvedAudit.results.find((row) => row.meta.replay_id === failure.id)!;
  expect(resolution.actor).toBe(me.id); expect(resolution.meta.resolution_code).toBe("acknowledged_no_change");
});
