import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Proposal layout", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
  });

  test("keeps aside cards from overlapping proposal totals while scrolling", async ({ page }) => {
    await page.goto("/bids");
    const firstBid = page.locator('a[href*="/bids/"]').filter({ hasText: /CBC-/ }).first();
    if ((await firstBid.count()) === 0) {
      test.skip(true, "No bids available for layout check");
      return;
    }

    const href = await firstBid.getAttribute("href");
    if (!href) {
      test.skip(true, "Bid link missing href");
      return;
    }

    const code = href.match(/\/bids\/([^/]+)/)?.[1];
    if (!code) {
      test.skip(true, "Could not parse bid code");
      return;
    }

    await page.goto(`/bids/${code}/proposal`);
    const aside = page.locator("aside").first();
    const totals = page.getByText("Grand total").first();

    if ((await totals.count()) === 0) {
      test.skip(true, "Proposal totals not rendered for this bid");
      return;
    }

    await page.mouse.wheel(0, 1200);
    await page.waitForTimeout(300);

    const asideBox = await aside.boundingBox();
    const totalsBox = await totals.boundingBox();
    if (!asideBox || !totalsBox) {
      test.skip(true, "Layout boxes unavailable");
      return;
    }

    const overlap =
      totalsBox.y < asideBox.y + asideBox.height &&
      totalsBox.y + totalsBox.height > asideBox.y &&
      totalsBox.x < asideBox.x + asideBox.width &&
      totalsBox.x + totalsBox.width > asideBox.x;

    expect(overlap).toBe(false);
  });
});
