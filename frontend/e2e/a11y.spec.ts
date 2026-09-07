import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { SEED, openRequestsTab, staffLogin } from "./helpers";

// WCAG 2.1 AA in a real browser (colour contrast included, which jsdom cannot compute).
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function expectClean(page: import("@playwright/test").Page) {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const summary = results.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length} nodes)`).join("\n");
  expect(results.violations, summary).toEqual([]);
}

test("public catalogue", async ({ page }) => {
  await page.goto(`/m/${SEED.slug}`);
  await expect(page.getByText(SEED.product).first()).toBeVisible();
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
