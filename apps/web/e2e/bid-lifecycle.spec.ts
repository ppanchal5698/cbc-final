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
    await page.getByLabel(/^job name/i).fill("E2E Test Bid");
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
    await expect(page.getByRole("dialog", { name: /create bid request/i })).toBeVisible();
  });
});

test.describe("Bid outcome", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
  });

  /** The headline stat beside a label in the board's summary bar. */
  async function statFor(page: import("@playwright/test").Page, label: string): Promise<number> {
    const stat = page.locator("span", { hasText: new RegExp(`^${label}$`) }).first();
    const value = await stat.locator("xpath=following-sibling::span[1]").innerText();
    return Number(value.replace(/[^0-9]/g, ""));
  }

  test("recording an outcome moves the win rate", async ({ page }) => {
    await page.goto("/bids");
    await openNewBid(page);
    const name = `E2E outcome ${Date.now()}`;
    await page.getByLabel(/^job name/i).fill(name);
    await page.getByRole("button", { name: /create/i }).click();
    await page.waitForURL(/\/bids\/[^/]+\/intake/);

    await page.goto("/bids");
    // Deltas, not absolutes: the board carries whatever bids the database
    // already had, and this must pass against any of them.
    const wonBefore = await statFor(page, "Won");

    const row = page.locator("a", { hasText: name }).first();
    await row.getByRole("button", { name: /click to mark won/i }).click();

    await expect(row.getByRole("button", { name: /click to mark lost/i })).toBeVisible();
    expect(await statFor(page, "Won")).toBe(wonBefore + 1);

    // Not bid clears the outcome, and the job leaves the win-rate denominator.
    await row.getByRole("button", { name: /click to mark not bid/i }).click();
    await expect(row.getByRole("button", { name: /no outcome applies/i })).toBeVisible();
    expect(await statFor(page, "Won")).toBe(wonBefore);
  });
});
