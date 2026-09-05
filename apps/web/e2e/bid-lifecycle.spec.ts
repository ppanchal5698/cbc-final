import { test, expect } from "@playwright/test";

import { credentials, openNewBid, signIn } from "./helpers";

test.describe("Bid board", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
  });

  test("filters bids via search input", async ({ page }) => {
    await page.goto("/bids");
    const search = page.getByRole("searchbox", { name: /search bids/i });
    await expect(search).toBeVisible();
    await search.fill("bid");
    await page.waitForURL(/q=bid/);
    await expect(page.getByRole("heading", { name: "Bid board" })).toBeVisible();
  });
});

test.describe("Bid lifecycle", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
  });

  test("creates a bid and navigates to intake", async ({ page }) => {
    await page.goto("/bids");
    await openNewBid(page);
    await page.getByLabel(/job name|name/i).fill("E2E Test Bid");
    await page.getByRole("button", { name: /create/i }).click();
    await page.waitForURL(/\/bids\/[^/]+\/intake/);
    await expect(page.getByText(/bid documents|upload/i).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test("shows inline validation when job name is empty", async ({ page }) => {
    await page.goto("/bids");
    await openNewBid(page);
    await page.getByRole("button", { name: /create bid/i }).click();
    await expect(page.getByText("Job name is required.")).toBeVisible();
    await expect(page.getByRole("dialog", { name: /new bid/i })).toBeVisible();
  });
});
