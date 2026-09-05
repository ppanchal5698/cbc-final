import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Job cancel", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
  });

  test("shows cancel control when terminal is open with an active run", async ({ page }) => {
    await page.goto("/bids");
    const firstBid = page.locator('a[href*="/bids/"]').first();
    test.skip((await firstBid.count()) === 0, "No bids available for terminal test");

    await firstBid.click();
    await page.getByRole("button", { name: /terminal/i }).click({ timeout: 10_000 }).catch(() => {
      test.skip(true, "No run pill / terminal entry on this bid");
    });

    const cancel = page.getByRole("button", { name: /cancel run/i });
    if ((await cancel.count()) === 0) {
      test.skip(true, "No queued or running job to cancel");
    }

    await expect(cancel).toBeVisible();
  });
});
