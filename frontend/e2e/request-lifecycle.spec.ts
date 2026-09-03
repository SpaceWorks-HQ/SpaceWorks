import { expect, test } from "@playwright/test";

import { EVIDENCE_FIXTURE, SEED, apiGet, apiLogin, makerspaceId, openRequestsTab, staffLogin } from "./helpers";

// The whole loan spine through the real UI, real presigned upload to object storage and the
// real state machine: pending -> accepted -> issued (box code + photo) -> returned (photo +
// remark). Runs on a freshly seeded makerspace (`manage.py seed_e2e --reset`).
test("accept, issue with box code and photo, then return with photo and remark", async ({ page, request }) => {
  await staffLogin(page);
  await openRequestsTab(page);

  const pending = page.locator("article").filter({ hasText: SEED.pendingRequestFor }).first();
  await expect(pending).toBeVisible();
  await pending.getByRole("button", { name: "Accept" }).click();
  const acceptDialog = page.getByRole("dialog");
  await acceptDialog.getByRole("button", { name: /^Accept/ }).click();
  await expect(acceptDialog).toBeHidden();

  const accepted = page.locator("article").filter({ hasText: SEED.pendingRequestFor }).first();
  await accepted.getByRole("button", { name: "Assign + issue" }).click();
  const issueDialog = page.getByRole("dialog");
  await issueDialog.getByRole("button", { name: "Enter code manually" }).click();
  await issueDialog.getByLabel("Container code").fill(SEED.boxCode);
  // Two controls carry "issue photo" in their name (the file input and the camera button).
  await issueDialog.locator('input[type="file"]').setInputFiles(EVIDENCE_FIXTURE);
  // The uploader finishes the presigned POST before the id is attached; wait for its done state.
  await expect(issueDialog.getByRole("status").filter({ hasText: "Photo uploaded" })).toBeVisible({ timeout: 20_000 });
  await issueDialog.getByRole("button", { name: "Assign + issue" }).click();
  await expect(issueDialog).toBeHidden({ timeout: 20_000 });

  const active = page.locator("section").filter({ hasText: "Active loans" });
  await expect(active.getByText(SEED.pendingRequestFor)).toBeVisible();
  await active.getByRole("button", { name: "Return" }).first().click();
  const returnDialog = page.getByRole("dialog");
  // A return re-identifies the container too, so the box code is entered again.
  await returnDialog.getByRole("button", { name: "Enter code manually" }).click();
  await returnDialog.getByLabel("Container code").fill(SEED.boxCode);
  await returnDialog.locator('input[type="file"]').setInputFiles(EVIDENCE_FIXTURE);
  await expect(returnDialog.getByRole("status").filter({ hasText: "Photo uploaded" })).toBeVisible({ timeout: 20_000 });
  await returnDialog.getByLabel("Remark").fill("All items back, checked by e2e.");
  await returnDialog.getByRole("button", { name: "Submit return" }).click();
  await expect(returnDialog).toBeHidden({ timeout: 20_000 });

  // The API is the source of truth for the transition, not the screen.
  const token = await apiLogin(request, SEED.manager.username, SEED.manager.password);
  const id = await makerspaceId(request, token);
  const loans = await apiGet<{ results: Array<{ requested_for: string }> }>(request, token, `/admin/makerspace/${id}/active-loans`);
  expect(loans.results.some((row) => row.requested_for === SEED.pendingRequestFor)).toBeFalsy();
  const acceptedQueue = await apiGet<{ results: Array<{ requested_for: string }> }>(request, token, `/admin/makerspace/${id}/accepted-requests`);
  expect(acceptedQueue.results.some((row) => row.requested_for === SEED.pendingRequestFor)).toBeFalsy();
});
