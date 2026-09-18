import { test, expect } from "@playwright/test";

import { credentials, openNewBid, signIn, submitNewBid } from "./helpers";

test.describe("Vendor quote requests", () => {
  test("an estimator opens a request as a draft and moves it to requested", async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);

    await page.goto("/bids");
    await openNewBid(page);
    await page.getByLabel(/^job name/i).fill(`E2E vendor RFQ ${Date.now()}`);
    await submitNewBid(page);
    await page.waitForURL(/\/bids\/([^/]+)\/intake/);
    const code = page.url().match(/\/bids\/([^/]+)\/intake/)?.[1];
    expect(code).toBeTruthy();

    await page.goto(`/bids/${code}/quote`);
    const panel = page.getByRole("region", { name: "Vendor quote requests" });
    await expect(panel).toBeVisible();

    await panel.getByRole("button", { name: /new request/i }).click();
    const rfqNumber = `RFQ-E2E-${Date.now()}`;
    await panel.getByLabel("RFQ number").fill(rfqNumber);
    await panel.getByLabel("Item description").fill("4070 HM door, 90 min");
    await panel.getByRole("button", { name: /open as draft/i }).click();

    await expect(panel.getByText(rfqNumber)).toBeVisible();
    await expect(panel.getByText("draft", { exact: true })).toBeVisible();

    await panel.getByRole("button", { name: "Mark requested" }).click();
    await expect(panel.getByText("requested", { exact: true })).toBeVisible();
    await expect(panel.getByRole("button", { name: "Mark awaiting" })).toBeVisible();
  });
});
