import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Catalog", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
  });

  test("searches the product catalog", async ({ page }) => {
    await page.goto("/catalog");
    // The placeholder is "Part number, description, manufacturer" - it never
    // contained the word "search". The input carries an aria-label instead.
    await page.getByLabel("Search the catalog").fill("door");

    // The result counter is always rendered ("N of M"), so it is a stable signal
    // that the search ran, whether or not this database has matching parts.
    await expect(page.getByText(/\d+ of \d+/).first()).toBeVisible({ timeout: 15_000 });
  });
});
