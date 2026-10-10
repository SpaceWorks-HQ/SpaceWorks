import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { SEED, openRequestsTab, staffLogin } from "./helpers";

// WCAG 2.1 AA in a real browser (colour contrast included, which jsdom cannot compute).
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function expectClean(page: Page) {
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.locator('[aria-label^="Loading"]')).toHaveCount(0);
  await expect(page.locator("p").filter({ hasText: /^Loading / })).toHaveCount(0);
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const summary = results.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length} nodes)`).join("\n");
  expect(results.violations, summary).toEqual([]);
}

for (const colorScheme of ["light", "dark"] as const) {
  test.describe(`${colorScheme} accessibility`, () => {
    test.use({ colorScheme });

    test("public catalogue and support footer", async ({ page }) => {
      await page.goto(`/m/${SEED.slug}`);
      await expect(page.getByText(SEED.product).first()).toBeVisible();
      await expect(page.getByRole("link", { name: "Contact support" })).toBeVisible();
      await expectClean(page);
    });

    test("staff login", async ({ page }) => {
      await page.goto(`/m/${SEED.slug}/admin`);
      await expect(page.getByLabel("Username")).toBeVisible();
      await expectClean(page);
    });

    test("staff requests console", async ({ page }) => {
      await staffLogin(page);
      await openRequestsTab(page);
      await expectClean(page);
    });

    test("public events and registration form", async ({ page }) => {
      await page.goto(`/m/${SEED.slug}/events`);
      await expect(page.getByRole("heading", { name: SEED.eventTitle })).toBeVisible();
      await expectClean(page);
      await page.getByRole("button", { name: "Register", exact: true }).click();
      await expect(page.getByRole("button", { name: "Close form" })).toBeVisible();
      await expectClean(page);
    });

    test("public bookings and request form", async ({ page }) => {
      await page.goto(`/m/${SEED.slug}/bookings`);
      await expect(page.getByRole("heading", { name: SEED.bookableSpace })).toBeVisible();
      await expectClean(page);
      await page.getByRole("button", { name: "Choose a time" }).click();
      await expect(page.getByRole("button", { name: "Close booking form" })).toBeVisible();
      await expectClean(page);
    });

    test("member joining screen, sign in and active member area", async ({ page }) => {
      await page.goto(`/m/${SEED.slug}/member`);
      await expect(page.getByRole("button", { name: "Sign in to join" })).toBeVisible();
      await expectClean(page);
      await page.getByRole("button", { name: "Sign in to join" }).click();
      await expect(page.getByRole("heading", { name: "Member sign in" })).toBeVisible();
      await expectClean(page);
      await page.getByLabel("Email", { exact: true }).fill(`${SEED.member.username}@e2e.local`);
      await page.getByLabel("Password", { exact: true }).fill(SEED.member.password);
      await page.getByRole("button", { name: "Sign in", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Membership", exact: true })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Presence", exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: "Contact support" })).toBeVisible();
      await expectClean(page);
    });

    for (const [path, heading, content] of [
      ["dashboard", "Dashboard", ""],
      ["inventory", "Inventory", SEED.product],
      ["members", "Members", ""],
      ["machines", "Machines", ""],
      ["events", "Events", SEED.eventTitle],
      ["bookings", "Bookings", SEED.bookableSpace],
      ["settings", "Makerspace settings", ""],
    ]) {
      test(`staff ${path} panel`, async ({ page }) => {
        await staffLogin(page);
        await page.goto(`/m/${SEED.slug}/admin/${path}`);
        await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
        if (content) await expect(page.getByText(content, { exact: true }).first()).toBeVisible();
        await expectClean(page);
      });
    }
  });
}
