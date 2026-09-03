import { expect, test } from "@playwright/test";

import { SEED, staffLogin } from "./helpers";

test.describe("staff authentication", () => {
  test("a wrong password is refused with a visible error", async ({ page }) => {
    await page.goto(`/m/${SEED.slug}/admin`);
    await page.getByLabel("Username").fill(SEED.manager.username);
    await page.getByLabel("Password").fill("not-the-password");
    await page.getByRole("button", { name: /sign in|log in/i }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByLabel("Password")).toBeVisible();
  });

  test("the seeded Space Manager signs in and lands on the console", async ({ page }) => {
    await staffLogin(page);
    await expect(page).toHaveURL(new RegExp(`/m/${SEED.slug}/admin`));
    await expect(page.getByText(SEED.makerspaceName).first()).toBeVisible();
  });
});
