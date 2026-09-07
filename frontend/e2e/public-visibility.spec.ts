import { expect, test } from "@playwright/test";

import { SEED } from "./helpers";

// The public catalogue must never expose storage locations, box codes or QR payloads
// (CLAUDE.md, "Public inventory must never expose"). The seed puts an unmistakable marker
// in the product's storage location and the box code is known, so the DOM can be searched.
test("the public catalogue shows the product but leaks nothing about where it lives", async ({ page }) => {
  await page.goto(`/m/${SEED.slug}`);
  await expect(page.getByText(SEED.product).first()).toBeVisible();
  const html = await page.content();
  expect(html).not.toContain(SEED.secretLocation);
  expect(html).not.toContain(SEED.boxCode);
  expect(html).not.toContain(SEED.boxLabel);
});

test("search narrows the catalogue and tolerates a typo", async ({ page }) => {
  await page.goto(`/m/${SEED.slug}`);
  // The catalogue applies the search on submit (Enter), not on every keystroke.
  const search = page.getByLabel("Search inventory");
  await search.fill("cordles dril");
  await search.press("Enter");
  await expect(page.getByText(SEED.product).first()).toBeVisible();
  await search.fill("zzzz-nothing-here");
  await search.press("Enter");
  await expect(page.getByText(SEED.product)).toHaveCount(0);
});
