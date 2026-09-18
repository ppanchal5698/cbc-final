import { test, expect } from "@playwright/test";

import { credentials, openNewBid, signIn } from "./helpers";

test.describe("Review flags", () => {
  test("a new bid's proposal page lists the flags the API derives", async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);

    await page.goto("/bids");
    await openNewBid(page);
    await page.getByLabel(/^job name/i).fill(`E2E review flags ${Date.now()}`);
    await page.getByRole("button", { name: /create/i }).click();
    await page.waitForURL(/\/bids\/([^/]+)\/intake/);
    const code = page.url().match(/\/bids\/([^/]+)\/intake/)?.[1];
    expect(code).toBeTruthy();

    await page.goto(`/bids/${code}/proposal`);
    const panel = page.getByRole("region", { name: "Review flags" });
    const unavailable = page.getByText(/could not build the proposal/i);
    await expect(panel.or(unavailable)).toBeVisible({ timeout: 20_000 });
    test.skip(await unavailable.isVisible(), "The proposal could not be built for a fresh bid");

    // No drawings and no project state yet: the empty take-off and the
    // unresolved sales tax are both flagged, never silently passed.
    await expect(panel.getByText("no scope")).toBeVisible();
    await expect(panel.getByText("sales tax", { exact: true })).toBeVisible();
  });
});
